"""Daily brief: pick the last 24h of incidents, write the article and social posts,
publish to imariners.com, then hand over to n8n for approval and the tweet on X.

  python -m tracker.brief              build + publish (+ n8n webhook)
  python -m tracker.brief --preview    build only, write out/brief.html, out/brief.json, out/featured.png
"""
from __future__ import annotations

import argparse
import html
import json
import re
from datetime import timedelta
from pathlib import Path

import requests

from . import incidents as store, llm
from .common import BRIEFS_DIR, PUBLISHED_STATUSES, ROOT, env, iso, log, no_em_dash, now_utc, parse_dt, read_json, write_json
from .image import render

OUT = ROOT / "out"
STATUS_LABEL = {
    "confirmed": "Confirmed",
    "reported": "Reported",
    "claimed": "Claimed",
}
STATUS_NOTE = {
    "confirmed": "confirmed by a neutral authority, the owner, or our own verification",
    "reported": "reported by independent media or by both sides",
    "claimed": "claimed by one side only, not independently confirmed",
}


def select(incidents: list[dict], since) -> tuple[list[dict], list[dict], list[dict]]:
    from .common import load_yaml

    include_naval = bool(load_yaml("regions.yaml").get("include_naval"))
    new, updated, corrections = [], [], []
    for inc in incidents:
        if inc.get("vessel_category") == "naval" and not include_naval:
            continue
        last = parse_dt(inc.get("last_updated"))
        if not last or last < since:
            continue
        if inc["status"] == "rejected" and inc.get("published_in"):
            corrections.append(inc)
        elif inc["status"] in PUBLISHED_STATUSES:
            (new if not inc.get("published_in") else updated).append(inc)
    return new, updated, corrections


def _e(x) -> str:
    return html.escape(str(x)) if x not in (None, "") else "Not known"


def incident_html(inc: dict) -> str:
    vessel = inc.get("vessel_name") or "Unnamed vessel"
    head = f"{vessel} ({inc['region']})"
    rows = [
        ("Status", f"<strong>{STATUS_LABEL[inc['status']]}</strong>: {STATUS_NOTE[inc['status']]}"),
        ("Vessel", " · ".join(_e(x) for x in (inc.get("vessel_type"), inc.get("flag") and f"{inc['flag']} flag",
                                               inc.get("imo") and f"IMO {inc['imo']}") if x) or "Not known"),
        ("When (UTC)", _e(inc.get("date_utc"))),
        ("Where", _e(inc.get("location_text"))),
        ("Attack type", _e(inc.get("attack_type"))),
        ("Damage", _e(inc.get("damage"))),
        ("Casualties", _e(inc.get("casualties"))),
        ("Claimed by / attributed to", _e(inc.get("attribution_claimed"))),
    ]
    sources = "".join(f"<li>{html.escape(name)}</li>" for name in
                      dict.fromkeys(s["source"] for s in inc["sources"] if s.get("source_type") != "satellite"))
    table = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows)
    return (f'<h3>{html.escape(no_em_dash(head))}</h3>\n<p>{html.escape(no_em_dash(inc.get("summary") or ""))}</p>\n'
            f'<table class="msb-incident"><tbody>{table}</tbody></table>\n<p><strong>Sources:</strong></p><ul>{sources}</ul>')


ALLOWED_TAGS = re.compile(r"</?(p|h2|h3|ul|ol|li|strong|em|a)(\s[^>]*)?>", re.I)
SOURCE_RANK = {"official": 0, "verification": 1, "media": 2, "local": 3, "osint": 4, "data": 5}


def _clean_html(text: str) -> str:
    """Keep only simple article tags from the model's HTML."""
    return re.sub(r"<[^>]+>", lambda m: m.group(0) if ALLOWED_TAGS.fullmatch(m.group(0)) else "", text or "")


def _facts(inc: dict) -> dict:
    fact = {k: inc.get(k) for k in ("region", "vessel_name", "vessel_type", "flag", "date_utc", "location_text",
                                    "attack_type", "damage", "casualties", "attribution_claimed", "status",
                                    "official_source_cited", "summary")}
    fact["reported_by"] = sorted({s["source"] for s in inc["sources"] if s.get("source_type") != "satellite"})[:8]
    if inc.get("verdict"):
        fact["checked_by_iMariners"] = inc["verdict"].get("note")
    return fact


def write_copy(day_label: str, new: list, updated: list, corrections: list) -> dict:
    """AI writes the news article, headline, excerpt and tweet from the structured facts only."""
    system = (
        "You are a news editor at iMariners, writing the daily maritime security news article for merchant "
        "seafarers, ship managers and maritime professionals. Style: a straight news report, like Reuters or "
        "Lloyd's List. Plain, calm British English. Use ONLY the facts given; never add vessels, numbers, causes, "
        "quotes or context that is not in the facts.\n"
        "Accuracy rules: attribute every claim in the text (e.g. 'UKMTO said', 'Russia's defence ministry claimed', "
        "'according to Splash247'). An incident with status 'claimed' must read as a claim by that party, never as "
        "fact. 'reported' means independent reporting without official confirmation. 'confirmed' means confirmed by "
        "a neutral authority, the owner or our own check. Never use em dashes or en dashes; use commas, colons or "
        "full stops. No hashtags in the article.\n"
        "Return JSON with keys:\n"
        '"title": a news headline, max 70 characters, about the most important incident of the day, no date, '
        "sentence case.\n"
        '"excerpt": meta description, max 155 characters.\n'
        '"key_points": 3 to 5 bullet points (plain text, each one sentence of at most 20 words) summarising the '
        "day for a reader who reads nothing else; the most important first; keep claim wording.\n"
        '"article_html": the article body in HTML using only <p>, <h2>, <ul>, <li>, <strong>. Readability rules: '
        "every paragraph at most 3 sentences and about 60 words; one incident per paragraph; short sentences. "
        "Structure: a lede paragraph of one or two sentences with the single most important news; a second short "
        "paragraph with the overall picture; then one <h2> section per region (Strait of Hormuz area first if it has "
        "incidents, then Black Sea), each incident in its own short paragraph with attribution; then "
        "<h2>What this means for crews</h2> with 2 or 3 practical sentences (follow UKMTO/JMIC guidance, report to "
        "UKMTO, company security procedures). 300 to 650 words. Do not repeat the key points word for word. "
        "No sources list (it is added automatically).\n"
        '"x_post": the tweet that shares the article: one or two short sentences, at most 200 characters, saying what '
        "happened and where; then a space and 3 or 4 hashtags chosen from #MaritimeSecurity #Shipping #Seafarers "
        "#BlackSea #StraitOfHormuz #Tanker #UKMTO #MaritimeNews, picking those that fit; no link (added automatically)."
    )
    user = json.dumps({"date": day_label, "new_incidents": [_facts(i) for i in new],
                       "updates_on_earlier_incidents": [_facts(i) for i in updated],
                       "corrections": [{"region": i["region"], "vessel_name": i.get("vessel_name"),
                                        "note": (i.get("verdict") or {}).get("note")} for i in corrections]},
                      ensure_ascii=False)
    try:
        copy = llm.chat_json(system, user, kind="brief", max_tokens=4000)
    except RuntimeError as exc:
        log.warning("AI article failed, using template: %s", exc)
        copy = {}
    n = len(new) + len(updated)
    by_region = {}
    for i in new + updated:
        by_region[i["region"]] = by_region.get(i["region"], 0) + 1
    summary = ", ".join(f"{r}: {c}" for r, c in by_region.items()) or "no verified attacks on vessels reported"
    fallback = {
        "title": f"Black Sea and Hormuz {'Shipping Attacks' if n else 'Maritime Security'}: {day_label}",
        "excerpt": f"Attacks on merchant ships in the Black Sea and Strait of Hormuz in the last 24 hours, {day_label}. {summary}.",
        "article_html": "",
        "key_points": [],
        "x_post": f"Maritime Security Brief, {day_label}: {summary}. #MaritimeSecurity #Shipping #Seafarers",
    }
    points = copy.get("key_points") if isinstance(copy.get("key_points"), list) else []
    out = {k: no_em_dash(str(copy.get(k) or fallback[k])) for k in fallback if k != "key_points"}
    out["key_points"] = [no_em_dash(str(p)).strip() for p in points if str(p).strip()][:5]
    out["title"] = out["title"][:90]
    out["article_html"] = _clean_html(out["article_html"])
    return out


def sources_html(incidents: list[dict]) -> str:
    """Compact source list: one line per incident, official first, at most 5 outlets.

    Outlets link to the article (nofollow) when the URL is the outlet's own page; Google News redirect URLs
    are shown as the outlet name only, so the article never carries long redirect links.
    """
    items = []
    for inc in incidents:
        srcs = [s for s in inc["sources"] if s.get("source_type") not in ("satellite", "verification")]
        srcs.sort(key=lambda s: (SOURCE_RANK.get(s.get("kind"), 9), s.get("side") != "neutral"))
        names, seen = [], set()
        for s in srcs:
            name = re.split(r"\s[-\u2013\u2014|:]\s", s["source"])[0].strip()  # "ABC News - Breaking..." -> "ABC News"
            key = re.sub(r"[^a-z0-9]", "", name.lower().replace("24/7", "247"))  # "Splash 24/7" == "Splash247"
            if not key or key in seen:
                continue
            seen.add(key)
            if "news.google.com" in s["url"]:
                names.append(html.escape(name))
            else:
                names.append(f'<a href="{html.escape(s["url"])}" rel="nofollow noopener" target="_blank">{html.escape(name)}</a>')
            if len(names) == 5:
                break
        label = inc.get("vessel_name") or (inc.get("vessel_type") or "vessel").capitalize()
        items.append(f"<li><strong>{html.escape(label)}, {html.escape(inc['region'])}</strong> "
                     f"({STATUS_LABEL[inc['status']].lower()}): {', '.join(names)}</li>")
    return "<h2>Sources</h2><ul>" + "".join(items) + "</ul>" if items else ""


def build(now=None) -> dict:
    now = now or now_utc()
    since = now - timedelta(hours=int(env("BRIEF_WINDOW_HOURS", "24")))
    day_label = now.strftime("%-d %B %Y")
    incidents = store.load()
    new, updated, corrections = select(incidents, since)
    copy = write_copy(day_label, new, updated, corrections)

    if copy["article_html"]:
        parts = []
        if copy["key_points"]:
            parts.append('<div class="msb-key-points"><p><strong>Key points</strong></p><ul>'
                         + "".join(f"<li>{html.escape(p)}</li>" for p in copy["key_points"]) + "</ul></div>")
        parts.append(copy["article_html"])
    else:  # the AI failed: fall back to the structured layout
        parts = [f"<p>In the 24 hours to 06:00 UTC on {html.escape(day_label)}: "
                 f"{html.escape(copy['excerpt'])}</p>"]
        parts += [incident_html(i) for i in new + updated]
    if corrections:
        parts.append("<h2>Corrections</h2><ul>" + "".join(
            f"<li>{html.escape(i.get('vessel_name') or i['id'])} ({html.escape(i['region'])}): an earlier report was "
            f"checked and not confirmed. {html.escape((i.get('verdict') or {}).get('note') or '')}</li>" for i in corrections) + "</ul>")
    if not (new or updated or corrections):
        parts.append("<p>No attacks on merchant vessels were reported in the Black Sea or the Strait of Hormuz area in the last 24 hours.</p>")
    if copy["article_html"]:
        parts.append(sources_html(new + updated))
    parts.append(
        "<p><em>How we report: iMariners monitors official advisories, maritime press, local news and public Telegram "
        "channels from both sides of each conflict, in five languages. <strong>Claimed</strong> means one side says it "
        "happened, <strong>reported</strong> means independent reporting, <strong>confirmed</strong> means a neutral "
        "authority, the owner or our own check confirms it. Seafarers should always follow UKMTO, JMIC and company "
        "security instructions.</em></p>"
    )
    body = no_em_dash("\n".join(parts))
    return {"date": now.date().isoformat(), "day_label": day_label, "generated_at": iso(now),
            **{k: copy[k] for k in ("title", "excerpt", "x_post")}, "html": body,
            "incident_ids": [i["id"] for i in new + updated], "correction_ids": [i["id"] for i in corrections],
            "counts": {"new": len(new), "updated": len(updated), "corrections": len(corrections)},
            "_incidents": new + updated}


def publish(brief: dict, image: Path) -> dict:
    from .wordpress import WordPress

    wp = WordPress()
    record_path = BRIEFS_DIR / f"{brief['date']}.json"
    record = read_json(record_path, {})
    mode = env("PUBLISH_MODE", "draft")
    if record.get("media_id") and record.get("image_url"):
        media_id, image_url = record["media_id"], record["image_url"]
    else:
        media_id, image_url = wp.upload_image(image, f"Map of {brief['title']}")
    post = wp.upsert_post(record.get("post_id"), {
        "title": brief["title"], "content": brief["html"], "excerpt": brief["excerpt"], "status": mode,
        "slug": f"maritime-security-brief-{brief['date']}", "featured_media": media_id,
        "categories": [wp.category_id(env("WP_CATEGORY_SLUG", "maritime-security"))],
    })
    preview_url = write_preview_page(brief, image_url)
    record.update(post_id=post["id"], media_id=media_id, image_url=image_url, preview_url=preview_url,
                  link=post["link"], status=post["status"],
                  **{k: brief[k] for k in ("title", "excerpt", "x_post", "incident_ids", "counts")})
    write_json(record_path, record)
    log.info("WordPress post %s (%s): %s", post["id"], post["status"], post["link"])
    return record


PAGES_URL = "https://imariner.github.io/maritime-security-tracker"
PREVIEW_STYLE = """body{font:17px/1.65 Georgia,serif;max-width:760px;margin:0 auto;padding:16px;color:#16202b;background:#fff}
.bar{font:13px system-ui;background:#fff6e0;border:1px solid #f0d58a;padding:10px 12px;border-radius:8px;margin:8px 0 18px}
h1{font:700 30px/1.2 system-ui;margin:12px 0 8px}h2{font:700 21px/1.3 system-ui;margin:28px 0 8px}
.ex{color:#4a5867;font-style:italic}img{max-width:100%;border-radius:8px}a{color:#0b5c8a}
.tw{font:15px/1.5 system-ui;background:#f3f6f9;border-radius:8px;padding:12px;white-space:pre-wrap}"""


def write_preview_page(brief: dict, image_url: str) -> str:
    """Unlisted, no-login copy of the draft for reading before approval (served by GitHub Pages)."""
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">'
            f"<title>Draft: {html.escape(brief['title'])}</title><style>{PREVIEW_STYLE}</style></head><body>"
            f'<div class="bar"><strong>DRAFT PREVIEW</strong>, not yet published. Approve or skip it in Telegram.</div>'
            + (f'<img src="{html.escape(image_url)}" alt="Map">' if image_url else "")
            + f"<h1>{html.escape(brief['title'])}</h1><p class=\"ex\">{html.escape(brief['excerpt'])}</p>{brief['html']}"
            f'<h2>Tweet</h2><div class="tw">{html.escape(brief["x_post"])} [link]</div></body></html>')
    (BRIEFS_DIR / f"{brief['date']}.html").write_text(page, encoding="utf-8")
    return f"{PAGES_URL}/preview/{brief['date']}.html"


def notify_n8n(record: dict) -> None:
    url = env("N8N_WEBHOOK_URL")
    if not url:
        log.info("No N8N_WEBHOOK_URL; skipping social posting")
        return
    payload = {**record, "needs_approval": record["status"] != "publish", "wp_url": env("WP_URL")}
    headers = {"X-Tracker-Token": env("N8N_WEBHOOK_TOKEN", "")}
    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    log.info("n8n webhook -> %s", resp.status_code)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--notify", action="store_true", help="only send today's saved brief to n8n")
    args = ap.parse_args()

    if args.notify:
        record = read_json(BRIEFS_DIR / f"{now_utc().date().isoformat()}.json", {})
        if record.get("post_id"):
            notify_n8n(record)
        else:
            log.info("No brief published today; nothing to send to n8n")
        return

    brief = build()
    image = render(parse_dt(brief["generated_at"]), brief.pop("_incidents"), OUT / f"brief-{brief['date']}.png")
    OUT.mkdir(exist_ok=True)
    (OUT / "brief.html").write_text(f"<h1>{html.escape(brief['title'])}</h1>\n{brief['html']}", encoding="utf-8")
    write_json(OUT / "brief.json", brief)
    if args.preview or not (env("WP_USER") and env("WP_APP_PASSWORD")):
        if not args.preview:
            log.warning("WordPress login not set (WP_USER, WP_APP_PASSWORD): brief built as a preview only, nothing published")
        log.info("Preview written to %s (download the 'brief' artifact from the Actions run)", OUT)
        return
    if not brief["incident_ids"] and not brief["correction_ids"] and env("PUBLISH_EMPTY_DAYS", "true") != "true":
        log.info("Nothing to report and PUBLISH_EMPTY_DAYS is off")
        return

    record = publish(brief, image)
    incidents = store.load()
    for inc in incidents:
        if inc["id"] in brief["incident_ids"] and brief["date"] not in inc.get("published_in", []):
            inc.setdefault("published_in", []).append(brief["date"])
    store.save(incidents)
    if env("NOTIFY_LATER") != "1":  # the workflow notifies after the preview page is online
        notify_n8n(record)


if __name__ == "__main__":
    main()

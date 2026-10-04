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
    """new: first seen in the window, attack within the last 7 days.
    updated: already published, and its status changed in the window (not merely another outlet repeating it).
    corrections: already published, and now rejected."""
    from .common import load_yaml

    cfg = load_yaml("regions.yaml")
    include_naval = bool(cfg.get("include_naval"))
    regions_on = {r["name"] for r in cfg.get("regions", []) if r.get("enabled")}
    oldest_event = since - timedelta(days=6)
    today = now_utc().date().isoformat()
    new, updated, corrections = [], [], []
    for inc in incidents:
        if inc.get("merged_into") or inc.get("region") not in regions_on or (
                inc.get("vessel_category") == "naval" and not include_naval):
            continue
        first = parse_dt(inc.get("first_seen"))
        changed = parse_dt(inc.get("status_changed_at"))
        event = parse_dt(inc.get("date_utc")) or first
        # A re-run on the same day rebuilds the same brief, so today's own publication does not count.
        if [d for d in inc.get("published_in") or [] if d != today]:
            if changed and changed >= since:
                (corrections if inc["status"] == "rejected" else updated if inc["status"] in PUBLISHED_STATUSES else []).append(inc)
        elif inc["status"] in PUBLISHED_STATUSES and first and first >= since and event and event >= oldest_event:
            new.append(inc)
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
        "You are a news editor at iMariners, writing the daily maritime security brief: what happened to merchant "
        "shipping in the war-risk areas (Black Sea, Red Sea and Gulf of Aden, Strait of Hormuz and the Gulf) in "
        "the last 24 hours, for seafarers on board and ship managers ashore. Style: a straight news report, like "
        "Reuters or Lloyd's List. Plain, calm British English. Use ONLY the facts given; never add vessels, numbers, "
        "causes, quotes or context that is not in the facts.\n"
        "Time rules: this is a 24-hour brief dated {date}. Give the date of every attack ('on 1 October'). When an "
        "attack happened more than a day before {date} but was only reported now, say so plainly ('UKMTO released "
        "late reports of attacks on 28 and 29 September'), never present it as new. For each area listed in "
        "quiet_areas, say in one sentence that no new attacks on merchant ships were reported there in the last "
        "24 hours.\n"
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
        "day for a reader who reads nothing else; the most important first; keep claim wording; always name the "
        "vessel and its flag when the facts give them.\n"
        '"article_html": the article body in HTML using only <p>, <h2>, <ul>, <li>, <strong>. Always name a vessel and its flag when the '
        "facts give them, in the headline too. Readability rules: "
        "every paragraph at most 3 sentences and about 60 words; one incident per paragraph and one ship per "
        "incident (never describe another ship inside a paragraph about a different one); short sentences. "
        "Structure: a lede paragraph of ONE sentence, at most 35 words, with the single most important news; a second short "
        "paragraph with the overall picture; then one <h2> section per region (Strait of Hormuz area first if it has "
        "incidents, then Black Sea), each incident in its own short paragraph with attribution; then "
        "<h2>What this means for crews</h2> with 2 or 3 practical sentences (follow UKMTO/JMIC guidance, report to "
        "UKMTO, company security procedures). 300 to 650 words. Do not repeat the key points word for word. "
        "No sources list (it is added automatically).\n"
        '"x_post": the tweet that shares the article: one or two short sentences, at most 200 characters, saying what '
        "happened and where; then a space and 3 or 4 hashtags chosen from #MaritimeSecurity #Shipping #Seafarers "
        "#BlackSea #StraitOfHormuz #RedSea #Tanker #UKMTO #MaritimeNews, picking those that fit; no link (added automatically)."
    )
    areas = {"Strait of Hormuz and the Gulf": {"Strait of Hormuz", "Persian Gulf", "Gulf of Oman"},
             "Red Sea and Gulf of Aden": {"Red Sea", "Gulf of Aden"}, "Black Sea": {"Black Sea", "Sea of Azov"}}
    active = {i["region"] for i in new + updated}
    quiet = [a for a, regs in areas.items() if not regs & active]
    system = system.replace("{date}", day_label)
    user = json.dumps({"date": day_label, "quiet_areas": quiet, "new_incidents": [_facts(i) for i in new],
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
        "title": f"{'Shipping attacks' if n else 'Maritime security'} in the Black Sea, Red Sea and Gulf: {day_label}",
        "excerpt": f"Attacks on merchant ships in the Black Sea, Red Sea and Gulf in the last 24 hours, {day_label}. {summary}.",
        "article_html": "",
        "key_points": [],
        "x_post": f"Maritime Security Brief, {day_label}: {summary}. #MaritimeSecurity #Shipping #Seafarers",
    }
    if copy.get("article_html"):
        copy = fact_check(copy, user)
    points = copy.get("key_points") if isinstance(copy.get("key_points"), list) else []
    out = {k: no_em_dash(str(copy.get(k) or fallback[k])) for k in fallback if k != "key_points"}
    out["key_points"] = [no_em_dash(str(p)).strip() for p in points if str(p).strip()][:5]
    out["fact_check"] = copy.get("fact_check", "not run")
    out["title"] = out["title"][:90]
    out["x_post"] = fit_tweet(out["x_post"])
    out["article_html"] = _clean_html(out["article_html"])
    return out


# iMariners palette: teal accent, navy headings, soft border, slate body text.
TEAL, NAVY, BORDER, BODY, MUTED = "#0A91AB", "#0B1E2D", "#DDE6EE", "#334155", "#64748B"


def key_points_html(points: list[str]) -> str:
    """'Key points' card: pill label and teal accent bar. Bullets come from the site's own list style
    (teal discs), so the card adds none of its own. Inline styles, so it looks the same in WordPress
    (kses keeps these properties) and on the preview page."""
    items = "".join(f'<li style="margin:0 0 12px;line-height:1.6;color:{BODY}">{html.escape(p)}</li>' for p in points)
    return (f'<div class="msb-key-points" style="border:1px solid {BORDER};border-left:5px solid {TEAL};'
            f'border-radius:16px;background-color:#FFFFFF;padding:22px 26px 12px;margin:0 0 28px">'
            f'<p style="display:inline-block;margin:0 0 16px;padding:6px 16px;border:1px solid {BORDER};'
            f'border-radius:999px;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;'
            f'color:{NAVY}">Key points</p>'
            f'<ul style="margin:0;padding-left:20px">{items}</ul></div>')


def map_figure_html(image_url: str, day_label: str) -> str:
    return (f'<figure class="msb-map" style="margin:0 0 28px">'
            f'<img src="{html.escape(image_url)}" alt="Map of reported attacks on ships, {html.escape(day_label)}" '
            f'width="1200" height="630" style="width:100%;height:auto;border-radius:12px" />'
            f'<figcaption style="font-size:13px;color:{MUTED};margin-top:8px">Incidents in the last 24 hours. '
            f'Positions are approximate unless reported. Map data &copy; OpenStreetMap contributors.</figcaption></figure>')


def with_map(body: str, image_url: str, day_label: str) -> str:
    """Put the map right after the key points card (or at the top when there is none)."""
    if not image_url or 'class="msb-map"' in body:
        return body
    fig = map_figure_html(image_url, day_label)
    end = body.find("</ul></div>") if 'class="msb-key-points"' in body else -1
    return body[: end + 11] + fig + body[end + 11 :] if end != -1 else fig + body


def fit_tweet(text: str, limit: int = 280 - 24) -> str:
    """Keep the tweet within X's limit once the link (23 characters plus a space) is added: drop trailing
    sentences before the hashtags, never the hashtags themselves."""
    if len(text) <= limit:
        return text
    tags = " ".join(w for w in text.split() if w.startswith("#"))
    body = " ".join(w for w in text.split() if not w.startswith("#"))
    sentences = re.split(r"(?<=[.;])\s+", body)
    while len(sentences) > 1 and len(" ".join(sentences) + " " + tags) > limit:
        sentences.pop()
    out = (" ".join(sentences) + " " + tags).strip()
    return out if len(out) <= limit else out[: limit - 1].rstrip() + "…"


def fact_check(copy: dict, facts_json: str) -> dict:
    """Second pass: check every sentence of the draft against the facts and correct what they do not support."""
    system = (
        "You are the fact-checker of a maritime security news desk. You get the FACTS (structured incident records) "
        "and a DRAFT (title, key points, article, tweet). Check every sentence of the draft against the facts. "
        "Correct anything not supported: wrong or missing dates, an attack presented as new when the facts show it "
        "happened earlier, a claim worded as fact, the wrong source credited (e.g. saying UKMTO named a ship when "
        "the facts say shipping media named it), details merged from two different incidents, places or vessels "
        "not in the facts, or blame not stated in the facts. Keep everything that is supported, keep the style, "
        "keep the HTML tags, never add new facts, never use em or en dashes.\n"
        'Return JSON: {"title": "...", "key_points": ["..."], "article_html": "...", "x_post": "...", '
        '"corrections": ["one short line per change you made"]}.'
    )
    draft = {k: copy.get(k) for k in ("title", "key_points", "article_html", "x_post")}
    try:
        checked = llm.chat_json(system, json.dumps({"FACTS": json.loads(facts_json), "DRAFT": draft}, ensure_ascii=False),
                                kind="brief", max_tokens=5000)
    except (RuntimeError, ValueError) as exc:
        log.warning("Fact-check skipped: %s", exc)
        copy["fact_check"] = "skipped"
        return copy
    fixes = [str(c) for c in checked.get("corrections") or [] if str(c).strip()
             and not re.search(r"\bno (changes|corrections)\b|nothing (to|was) (change|correct)", str(c), re.I)]
    for k in ("title", "article_html", "x_post"):
        if isinstance(checked.get(k), str) and checked[k].strip():
            copy[k] = checked[k]
    if isinstance(checked.get("key_points"), list) and checked["key_points"]:
        copy["key_points"] = checked["key_points"]
    copy["fact_check"] = f"{len(fixes)} correction(s)" if fixes else "no corrections needed"
    for f in fixes:
        log.info("Fact-check: %s", f[:200])
    return copy


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
            parts.append(key_points_html(copy["key_points"]))
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
        parts.append("<p>No attacks on merchant vessels were reported in the Black Sea, the Red Sea or the Gulf area in the last 24 hours.</p>")
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
            "fact_check": copy.get("fact_check", "not run"),
            "incident_ids": [i["id"] for i in new + updated], "correction_ids": [i["id"] for i in corrections],
            "counts": {"new": len(new), "updated": len(updated), "corrections": len(corrections)},
            "_incidents": new + updated}


def publish(brief: dict, image: Path) -> dict:
    from .wordpress import WordPress

    wp = WordPress()
    record_path = BRIEFS_DIR / f"{brief['date']}.json"
    record = read_json(record_path, {})
    mode = env("PUBLISH_MODE", "draft")
    # a fresh upload every run: a same-day rerun can carry different incidents
    media_id, image_url = wp.upload_image(image, f"Map of {brief['title']}")
    brief["html"] = with_map(brief["html"], image_url, brief["day_label"])
    post = wp.upsert_post(record.get("post_id"), {
        "title": brief["title"], "content": brief["html"], "excerpt": brief["excerpt"], "status": mode,
        "slug": f"maritime-security-brief-{brief['date']}", "featured_media": media_id,
        "categories": [wp.category_id(env("WP_CATEGORY_SLUG", "maritime-security"))],
    })
    brief["quality"] = quality_report(brief, store.load())
    log.info("Quality: %s", brief["quality"]["summary"])
    preview_url = write_preview_page(brief, image_url)  # brief["html"] already carries the map
    record.update(post_id=post["id"], media_id=media_id, image_url=image_url, preview_url=preview_url,
                  link=post["link"], status=post["status"],
                  **{k: brief[k] for k in ("title", "excerpt", "x_post", "incident_ids", "counts", "fact_check")},
                  quality=brief["quality"]["summary"])
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
            f'<div class="bar"><strong>DRAFT PREVIEW</strong>, not yet published. Approve or skip it in Telegram.'
            f'<br>Checks: {html.escape((brief.get("quality") or {}).get("summary", "not run"))}</div>'
            + f"<h1>{html.escape(brief['title'])}</h1><p class=\"ex\">{html.escape(brief['excerpt'])}</p>{brief['html']}"
            f'<h2>Tweet</h2><div class="tw">{html.escape(brief["x_post"])} [link]</div></body></html>')
    (BRIEFS_DIR / f"{brief['date']}.html").write_text(page, encoding="utf-8")
    version = re.sub(r"\D", "", brief["generated_at"])[-6:]  # new link each rebuild, so no cached copy is shown
    return f"{PAGES_URL}/preview/{brief['date']}.html?v={version}"


def quality_report(brief: dict, incidents: list[dict]) -> dict:
    """Fixed checklist shown in the approval message, so a quick glance tells how carefully to read."""
    from .incidents import has_official

    cut = now_utc() - timedelta(hours=48)
    used = [i for i in incidents if i["id"] in brief["incident_ids"]]
    official_recent = [i for i in incidents if has_official(i) and i.get("status") not in ("merged", "rejected")
                       and (parse_dt(i.get("date_utc")) or now_utc()) >= cut]
    covered = [i for i in official_recent if i["id"] in brief["incident_ids"]]
    undated = [i for i in used if not parse_dt(i.get("date_utc")) or i.get("date_approx")]
    claims = [i for i in used if i["status"] == "claimed"]
    unattributed = [i for i in claims if not i.get("attribution_claimed") and not any(
        s.get("kind") == "official" for s in i["sources"])]
    single = [i for i in used if len({s["source"] for s in i["sources"] if s.get("source_type") != "satellite"}) < 2
              and not has_official(i)]
    verified = [i for i in used if i.get("verdict") or has_official(i)]
    text = brief["html"] + brief["title"] + brief["x_post"]
    dashes = len(re.findall("[\u2014\u2013]", text))
    tweet_len = len(brief["x_post"]) + 24
    checks = {
        "dates": "ok" if not undated else f"{len(undated)} approximate",
        "attribution": "ok" if not unattributed else f"{len(unattributed)} claims without a named source",
        "official coverage": f"{len(covered)}/{len(official_recent)}" + (" ok" if len(covered) == len(official_recent) else " MISSING"),
        "verified": f"{len(verified)}/{len(used)}",
        "single-source items": str(len(single)),
        "fact-check": brief.get("fact_check", "not run"),
        "tweet": f"{tweet_len}/280" + (" ok" if tweet_len <= 280 else " TOO LONG"),
        "dashes": "ok" if not dashes else f"{dashes} found",
    }
    flags = sum(1 for k, v in checks.items() if "MISSING" in v or "TOO LONG" in v or "found" in v or "without" in v)
    summary = ("all checks passed" if not flags else f"{flags} check(s) need attention") + ": " + \
        "; ".join(f"{k} {v}" for k, v in checks.items())
    return {"checks": checks, "summary": summary}


def notify_n8n(record: dict) -> None:
    url = env("N8N_WEBHOOK_URL")
    if not url:
        log.info("No N8N_WEBHOOK_URL; skipping social posting")
        return
    payload = {**record, "needs_approval": record["status"] != "publish", "wp_url": env("WP_URL")}
    headers = {"X-Tracker-Token": env("N8N_WEBHOOK_TOKEN", "")}
    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    log.info("n8n webhook -> %s", resp.status_code)


def refresh_image(day: str) -> None:
    """Redraw the map for a brief already on WordPress and swap it into the post (inline and featured).
    Text and status are left exactly as they are."""
    from datetime import datetime, timezone

    from .wordpress import WordPress

    record_path = BRIEFS_DIR / f"{day}.json"
    record = read_json(record_path, {})
    if not record.get("post_id") or not record.get("image_url"):
        raise SystemExit(f"No published brief with an image for {day}")
    by_id = {i["id"]: i for i in store.load()}
    chosen = [by_id[i] for i in record.get("incident_ids", []) if i in by_id]
    image = render(datetime.fromisoformat(day).replace(tzinfo=timezone.utc), chosen, OUT / f"brief-{day}.png")
    wp = WordPress()
    post = wp._req("GET", f"/posts/{record['post_id']}", params={"context": "edit"})
    content = post["content"]["raw"]
    if record["image_url"] not in content:
        raise SystemExit(f"The post does not contain the recorded image {record['image_url']}; nothing changed")
    media_id, image_url = wp.upload_image(image, f"Map of {record.get('title', 'the brief')}")
    # only fields that change: the post keeps its title, text and status
    wp._req("POST", f"/posts/{record['post_id']}", json={
        "content": content.replace(record["image_url"], image_url), "featured_media": media_id})
    record.update(media_id=media_id, image_url=image_url)
    write_json(record_path, record)
    log.info("Post %s now uses %s", record["post_id"], image_url)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--notify", action="store_true", help="only send today's saved brief to n8n")
    ap.add_argument("--refresh-image", metavar="YYYY-MM-DD", help="redraw the map of a published brief and swap it in")
    args = ap.parse_args()

    if args.refresh_image:
        refresh_image(args.refresh_image)
        return

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
    llm.log_usage("brief")
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

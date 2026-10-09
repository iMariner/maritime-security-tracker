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
import time
from datetime import timedelta
from pathlib import Path

import requests

from . import incidents as store, lessons, llm
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
        changed = max(filter(None, (parse_dt(inc.get("status_changed_at")), parse_dt(inc.get("news_changed_at")))),
                      default=None)
        event = parse_dt(inc.get("date_utc")) or first
        # A re-run on the same day rebuilds the same brief, so today's own publication does not count.
        earlier_briefs = [d for d in inc.get("published_in") or [] if d != today]
        if earlier_briefs:
            # An update must be newer than the brief that last carried it. A change made while that brief was
            # being prepared (its morning editor check) is already in it, so it is not news the next day.
            if changed and changed >= max(since, _sent_at(max(earlier_briefs)) or since):
                (corrections if inc["status"] == "rejected" else updated if inc["status"] in PUBLISHED_STATUSES else []).append(inc)
        elif inc["status"] in PUBLISHED_STATUSES and first and first >= since and event and event >= oldest_event:
            new.append(inc)
    return new, updated, corrections


_SENT: dict = {}


def _sent_at(day: str):
    """When that day's brief went out for approval (or was last built), from its record."""
    if day not in _SENT:
        rec = read_json(BRIEFS_DIR / f"{day}.json", {})
        _SENT[day] = parse_dt(rec.get("notified")) or parse_dt(rec.get("generated_at"))
    return _SENT[day]


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
    fact = {k: inc.get(k) for k in ("region", "vessel_name", "vessel_type", "flag", "imo", "date_utc", "location_text",
                                    "attack_type", "damage", "casualties", "attribution_claimed", "status",
                                    "official_source_cited", "summary", "position_note")}
    fact["reported_by"] = sorted({s["source"] for s in inc["sources"] if s.get("source_type") != "satellite"})[:8]
    if inc.get("verdict"):
        fact["checked_by_iMariners"] = inc["verdict"].get("note")
    return fact


AREAS = {"Strait of Hormuz and the Gulf": {"Strait of Hormuz", "Persian Gulf", "Gulf of Oman"},
         "Red Sea and Gulf of Aden": {"Red Sea", "Gulf of Aden"}, "Black Sea": {"Black Sea", "Sea of Azov"}}


def _hurt(inc: dict) -> bool:
    """Someone killed, injured or missing, so the attack is news even when it is a few days old."""
    return bool(re.search(r"kill|dead|died|injur|wound|missing|casualt", str(inc.get("casualties") or ""), re.I)
                and not re.search(r"\bno (injur|casualt)", str(inc.get("casualties") or ""), re.I))


def _day(iso_date: str) -> str:
    d = parse_dt(iso_date)
    return d.strftime("%-d %B") if d else "earlier"


def tracker_context(incidents: list[dict], now) -> list[dict]:
    """Counts from our own data for context and the crew section: merchant ships reported hit per area in the
    last 7 days and in the 7 days before that."""
    out = []
    for area, regions in AREAS.items():
        hits = [(i, d) for i in incidents if i.get("region") in regions and i.get("status") in ("confirmed", "reported")
                and not i.get("merged_into") and i.get("vessel_category") != "naval"
                # a specific ship, not a statistic such as "Iran fired 360 missiles at shipping"
                and any(i.get(k) for k in ("vessel_name", "imo", "flag", "vessel_type"))
                and (d := parse_dt(i.get("date_utc")))]
        week = [i for i, d in hits if now - timedelta(days=7) <= d <= now]
        before = [i for i, d in hits if now - timedelta(days=14) <= d < now - timedelta(days=7)]
        if week or before:
            out.append({"area": area, "merchant_ships_reported_hit_in_last_7_days": len(week),
                        "merchant_ships_reported_hit_in_the_7_days_before": len(before),
                        "named_ships": sorted({i["vessel_name"] for i in week if i.get("vessel_name")})})
    return out


def write_copy(day_label: str, new: list, updated: list, corrections: list,
               incidents: list | None = None, now=None, editor_notes: list | None = None) -> dict:
    """AI writes the news article, headline, excerpt and tweet from the structured facts only."""
    system = (
        "You are the senior news editor of the iMariners Security Desk, writing the daily maritime security brief "
        "for seafarers on board and ship managers ashore: what happened to merchant shipping in the war-risk areas "
        "(Black Sea, Red Sea and Gulf of Aden, Strait of Hormuz and the Gulf) in the last 24 hours. It must read "
        "like a Reuters or Lloyd's List news story, not a report generator. Plain, calm British English. Use ONLY "
        "the facts given (incidents, tracker_context, corrections); never add vessels, numbers, causes, quotes, "
        "advice or background that is not in them.\n"
        "Time rules: the brief is dated {date}. Give the date of every attack ('on 4 October'). An attack from more "
        "than a day before {date} that was only reported now must say so plainly, never read as new. For each area "
        "in quiet_areas, one sentence that no new attacks on merchant ships were reported there in the last 24 "
        "hours.\n"
        "Accuracy rules: attribute every claim, and credit each detail to the source that gave it (when a ship's "
        "name comes from a security firm or the press, say so; never write that UKMTO named it). 'claimed' must read "
        "as one party's claim, never as fact. 'reported' means independent reporting without official confirmation. "
        "'confirmed' means a neutral authority, the owner or our own check confirms it. Never use em or en dashes.\n"
        "Editor notes: editor_notes come from the editor who opened the original sources. Where they conflict with "
        "the incident facts, the notes win. Follow every note in every layer (headline, standfirst, key points, "
        "article, tweet): fix the date, the credited source or the paragraph a detail belongs to, exactly as the "
        "note says. When a note says sources give different dates, give each source and its date. Never mention the "
        "notes themselves.\n"
        "Newsroom style rules:\n"
        "- Never repeat a sentence or phrase between the headline, standfirst, key points and lede. Each layer adds "
        "something new.\n"
        "- No fact twice: each detail (a date, a casualty figure, who confirmed it) appears once in the article body. "
        "The key points are the summary; the lede and area sections must not restate a key point in other words, they "
        "add what the key points leave out (where exactly, ship type and owner, what is still unknown). Credit a "
        "source once per incident, not in every sentence.\n"
        "- earlier_this_week holds older attacks first reported now in which no one was hurt: give them one sentence "
        "each, in one short paragraph starting 'Earlier in the week,' at the end of their area section. Never put "
        "them in the headline, standfirst or key points.\n"
        "- Name the ship as early as possible and describe it the way a news story does: 'the Liberia-flagged LR2 "
        "tanker Lipsi' (ship names in normal capitalisation, not ALL CAPS; keep IMO numbers out of the headline).\n"
        "- Vary attribution: say who said it once per paragraph at most ('UKMTO said', 'according to', 'the agency "
        "added'). Never start a sentence or paragraph with a warning number ('UKMTO warning 150-26, dated ...'); mention a warning number once, "
        "inside a sentence, if at all.\n"
        "- Use tracker_context (counts from the iMariners incident tracker) for one sentence of context in the "
        "second paragraph, credited to 'the iMariners tracker' (e.g. 'It is the fifth merchant ship reported hit in "
        "the Strait of Hormuz in seven days, according to the iMariners tracker'). Do not invent trends.\n"
        "- Order by news value, most serious first (damage or casualties before near misses).\n"
        "Return JSON with keys:\n"
        '"title": the headline, at most 80 characters, sentence case, active voice, present tense, about ONE story: '
        "the most serious incident, naming the ship when known. Never join two incidents with 'as' or 'while'; the "
        "standfirst and key points carry the rest.\n"
        '"excerpt": the standfirst, one sentence of at most 30 words that adds detail beyond the headline (where, '
        "damage, crew); also used as the meta description.\n"
        '"key_points": 3 to 5 bullets, each a different fact in at most 18 words, most important first: the main '
        "attack with damage and crew status, the ship's identity, the second incident, the wider picture, quiet "
        "areas. No bullet that only says details are missing.\n"
        '"article_html": the story in HTML using only <p>, <h2>, <ul>, <li>, <strong>. Structure: (1) lede, one '
        "sentence, at most 35 words, the five Ws of the main incident, worded differently from the headline; (2) a "
        "second paragraph with the overall picture and one sentence from tracker_context; (3) one <h2> section per "
        "area with incidents, most serious first, each incident in one or two short paragraphs (max 3 sentences, "
        "about 60 words each) with ship identity, time if known, place, damage, crew, who said it, and what is not "
        "yet known (attacker, cause) in one sentence. The section must add what the lede did not say (ship details, "
        "owner or manager, attribution, what is unknown) instead of restating it; (4) <h2>What crews should know</h2>: "
        "two or three sentences built only from the facts: first the trend for each area with attacks, comparing "
        "merchant_ships_reported_hit_in_last_7_days with merchant_ships_reported_hit_in_the_7_days_before from "
        "tracker_context in plain words (credited to the iMariners tracker); then where today's attacks happened "
        "(the places and distances in the incidents, for example 'inside Bulgaria's exclusive economic zone, about 70 "
        "nautical miles off Byala'); then: report any attack or suspicious approach to UKMTO, and follow UKMTO and "
        "JMIC advisories and company security instructions. Never invent advice, routes, ports, distances or "
        "measures; specific guidance only if it appears word for word in the facts. 250 to 550 words. No sources list and no corrections section "
        "(both are added automatically).\n"
        '"correction_notes": one plain sentence per item in corrections, in news style, using '
        "first_published_in_brief_of, what_we_reported and why_it_was_wrong: 'Our <date> brief reported <what we "
        "reported>; <what the check found>.' Empty list if none.\n"
        '"x_post": the tweet: one or two short sentences, at most 200 characters, naming the ship and place; then '
        "3 or 4 hashtags chosen from #MaritimeSecurity #Shipping #Seafarers #BlackSea #StraitOfHormuz #RedSea #Tanker "
        "#UKMTO #MaritimeNews; no link (added automatically)."
    )
    # Older attacks first reported now, with no one hurt, get one line each instead of a full paragraph
    cut = (now or now_utc()) - timedelta(hours=48)
    earlier = [i for i in new if (d := parse_dt(i.get("date_utc"))) and d < cut and not _hurt(i)]
    new = [i for i in new if i not in earlier]
    active = {i["region"] for i in new + updated + earlier}
    quiet = [a for a, regs in AREAS.items() if not regs & active]
    system = system.replace("{date}", day_label) + lessons.prompt_block("writing")
    user = json.dumps({"date": day_label, "quiet_areas": quiet, "editor_notes": list(editor_notes or []),
                       "new_incidents": [_facts(i) for i in new],
                       "updates_on_earlier_incidents": [_facts(i) for i in updated],
                       "earlier_this_week": [_facts(i) for i in earlier],
                       "tracker_context": tracker_context(incidents or [], now or now_utc()),
                       "corrections": [{"region": i["region"], "vessel_name": i.get("vessel_name"),
                                        "first_published_in_brief_of": (i.get("published_in") or [None])[0],
                                        "what_we_reported": i.get("summary"),
                                        "why_it_was_wrong": (i.get("verdict") or {}).get("note")} for i in corrections]},
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
    notes = copy.get("correction_notes") if isinstance(copy.get("correction_notes"), list) else []
    out["correction_notes"] = [no_em_dash(str(c)).strip() for c in notes if str(c).strip()]
    out["fact_check"] = copy.get("fact_check", "not run")
    out["fact_check_fixes"] = copy.get("fact_check_fixes") or []
    out["title"] = out["title"][:90]
    out["x_post"] = fit_tweet(out["x_post"])
    out["article_html"] = _clean_html(out["article_html"])
    out["quiet_areas"] = quiet
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
    tag_list = tags.split()
    body = " ".join(sentences)
    while tag_list and len(body + " " + " ".join(tag_list)) > limit and len(tag_list) > 1:
        tag_list.pop()  # fewer hashtags before cutting any words
    tags = " ".join(tag_list)
    room = limit - (len(tags) + 1 if tags else 0)
    if len(body) > room:  # still too long: cut the sentence at a word boundary, never inside a hashtag
        body = body[: max(room - 1, 0)].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return (body + " " + tags).strip()


def fact_check(copy: dict, facts_json: str) -> dict:
    """Second pass: check every sentence of the draft against the facts and correct what they do not support."""
    system = (
        "You are the fact-checker of a maritime security news desk. You get the FACTS (structured incident records) "
        "and a DRAFT (title, excerpt, key points, article, tweet). Check every sentence of the draft against the facts. "
        "Correct anything not supported: wrong or missing dates, an attack presented as new when the facts show it "
        "happened earlier, a claim worded as fact, the wrong source credited (e.g. saying UKMTO named a ship when "
        "the facts say shipping media named it), details merged from two different incidents, places or vessels "
        "not in the facts, or blame not stated in the facts. FACTS.editor_notes come from the editor who checked the "
        "original sources: they overrule the incident records, and the draft must follow every one of them. Keep everything that is supported, keep the style, "
        "keep the HTML tags, never add new facts, never use em or en dashes.\n"
        "Keep the news style: do not make sentences longer or add attribution to sentences that already have it in "
        "the same paragraph. "
        'Return JSON: {"title": "...", "excerpt": "...", "key_points": ["..."], "article_html": "...", "x_post": "...", "correction_notes": ["..."], '
        '"corrections": ["one short line per change you made"]}.'
    )
    system += lessons.prompt_block("writing")
    draft = {k: copy.get(k) for k in ("title", "excerpt", "key_points", "article_html", "x_post", "correction_notes")}
    try:
        checked = llm.chat_json(system, json.dumps({"FACTS": json.loads(facts_json), "DRAFT": draft}, ensure_ascii=False),
                                kind="brief", max_tokens=5000)
    except (RuntimeError, ValueError) as exc:
        log.warning("Fact-check skipped: %s", exc)
        copy["fact_check"] = "skipped"
        return copy
    fixes = [str(c) for c in checked.get("corrections") or [] if str(c).strip()
             and not re.search(r"\bno (changes|corrections)\b|nothing (to|was) (change|correct)", str(c), re.I)]
    for k in ("title", "excerpt", "article_html", "x_post"):
        if isinstance(checked.get(k), str) and checked[k].strip():
            copy[k] = checked[k]
    for k in ("key_points", "correction_notes"):
        if isinstance(checked.get(k), list) and checked[k]:
            copy[k] = checked[k]
    copy["fact_check"] = f"{len(fixes)} correction(s)" if fixes else "no corrections needed"
    copy["fact_check_fixes"] = [f[:300] for f in fixes]  # the learning log: what the writer got wrong
    for f in fixes:
        log.info("Fact-check: %s", f[:200])
    return copy


OFFICIAL_SITES = re.compile(r"https?://(www\.)?(ukmto\.org|jmic|maritime\.dot\.gov|imo\.org|centcom\.mil)", re.I)
OUTLETS = {"ukmto.org": "UKMTO", "maritime.dot.gov": "MARAD", "imo.org": "IMO", "rivieramm.com": "Riviera Maritime Media",
           "portnews.ru": "PortNews", "maritime-executive.com": "The Maritime Executive", "tradewinds": "TradeWinds",
           "lloydslist": "Lloyd's List", "splash247.com": "Splash247", "seatrade-maritime.com": "Seatrade Maritime",
           "gcaptain.com": "gCaptain", "aa.com.tr": "Anadolu Agency", "reuters.com": "Reuters"}


def outlet_name(s: dict) -> str:
    """'ABC News - Breaking...' -> 'ABC News'; a bare web address or a verification link -> the outlet's name."""
    url = s.get("url", "")
    for key, name in OUTLETS.items():
        if key in url and "news.google.com" not in url:
            return name
    name = re.split(r"\s[-\u2013\u2014|:]\s", s.get("source") or "")[0].strip()
    if re.fullmatch(r"[\w.-]+\.[a-z]{2,}", name):  # a domain such as 'example-news.com'
        name = re.sub(r"^(www|en)\.", "", name).split(".")[0].replace("-", " ").title()
    return name


_TRUSTED = None


def trusted_outlet(s: dict) -> str | None:
    """The outlet's public name if it is on config/trusted_outlets.yaml (or an official source), else None.
    Keys with a dot match the web address; other keys match the collected outlet name exactly."""
    global _TRUSTED
    if _TRUSTED is None:
        from .common import load_yaml
        _TRUSTED = load_yaml("trusted_outlets.yaml").get("trusted") or []
    url = s.get("url") or ""
    host = "" if "news.google.com" in url else re.sub(r"^https?://([^/]+).*$", r"\1", url).lower()
    raw = re.split(r"\s[-\u2013\u2014|:]\s", s.get("source") or "")[0].strip().lower()
    norm = lambda x: re.sub(r"[\W_]", "", re.sub(r"^(www\.|the )", "", x))
    name = norm(raw)
    bare = norm(re.sub(r"\s+news$", "", raw))  # "TradeWinds News" / "Seatrade Maritime News" -> the outlet
    for t in _TRUSTED:
        for key in t.get("match") or []:
            key = str(key).lower()
            if (host and key in host) or (name and name == norm(key)) or (bare and bare == norm(key)):
                return t["name"]
    if s.get("kind") == "official":
        return outlet_name(s)
    return None


def sources_html(incidents: list[dict]) -> str:
    """Compact source list: one line per incident, official first, at most 4 outlets, only trusted outlets
    (config/trusted_outlets.yaml). Local, partisan and aggregator sources stay internal; when an incident has
    no trusted outlet the line says so instead of listing them.

    Outlets link to the article (nofollow) when the URL is the outlet's own page; Google News redirect URLs
    are shown as the outlet name only, so the article never carries long redirect links.
    """
    items = []
    for inc in incidents:
        srcs = [s for s in inc["sources"] if s.get("source_type") not in ("satellite", "verification")
                or OFFICIAL_SITES.search(s.get("url", ""))]
        srcs.sort(key=lambda s: (SOURCE_RANK.get(s.get("kind"), 9), s.get("side") != "neutral"))
        names, seen = [], set()
        for s in srcs:
            name = trusted_outlet(s)
            if not name:
                continue
            key = re.sub(r"[\W_]", "", name.lower().replace("24/7", "247"))  # "Splash 24/7" == "Splash247"; keeps Arabic names
            if not key or key in seen:
                continue
            seen.add(key)
            if "news.google.com" in s["url"]:
                names.append(html.escape(name))
            else:
                names.append(f'<a href="{html.escape(s["url"])}" rel="nofollow noopener" target="_blank">{html.escape(name)}</a>')
            if len(names) == 4:
                break
        if not names:
            names = ["local and social media reports, not yet confirmed by a major outlet"]
        label = (inc["vessel_name"].title() if inc.get("vessel_name") else (inc.get("vessel_type") or "vessel").capitalize())
        items.append(f"<li><strong>{html.escape(label)}, {html.escape(inc['region'])}</strong> "
                     f"({STATUS_LABEL[inc['status']].lower()}): {', '.join(names)}</li>")
    return "<h2>Sources</h2><ul>" + "".join(items) + "</ul>" if items else ""


# Ways each area is named in an article. "the Gulf" must not catch "the Gulf of Aden" or "the Gulf of Oman".
AREA_WORDS = {
    "Strait of Hormuz and the Gulf": r"hormuz|persian gulf|arabian gulf|gulf of oman|\bthe gulf\b(?! of)",
    "Red Sea and Gulf of Aden": r"red sea|gulf of aden|bab el-?mandeb",
    "Black Sea": r"black sea|sea of azov",
}
QUIET_CLAIM = re.compile(r"\bno (?:new )?(?:attacks?|incidents?)\b|\bwas quiet\b|\bremained quiet\b", re.I)


def _contradicts(sentence: str, active: list[str]) -> bool:
    """A sentence saying an area had no attacks while the brief has an incident there."""
    return bool(QUIET_CLAIM.search(sentence)) and any(re.search(AREA_WORDS[a], sentence, re.I) for a in active)


def enforce_consistency(copy: dict, included: list[dict]) -> tuple[list[str], list[str]]:
    """Checks the written brief against the data, in code (no AI). Sentences that call an area quiet while the
    brief reports an incident there are removed. Returns (fixed, problems): problems are left for the owner."""
    quiet = set(copy.get("quiet_areas") or [])
    active = [a for a in AREA_WORDS if a not in quiet]
    fixed, problems = [], []
    keep = []
    for p in copy.get("key_points") or []:
        if _contradicts(p, active):
            fixed.append(f"removed key point '{p[:70]}'")
        else:
            keep.append(p)
    copy["key_points"] = keep

    def clean_block(m):
        inner = m.group(2)
        parts = re.split(r"(?<=[.!?])\s+", inner)
        good = [s for s in parts if not _contradicts(re.sub(r"<[^>]+>", "", s), active)]
        for s in parts:
            if s not in good:
                fixed.append(f"removed '{re.sub(r'<[^>]+>', '', s)[:70]}'")
        return f"{m.group(1)}{' '.join(good)}{m.group(3)}" if good else ""

    copy["article_html"] = re.sub(r"(<(?:p|li)[^>]*>)(.*?)(</(?:p|li)>)", clean_block, copy.get("article_html") or "",
                                  flags=re.S)
    for field in ("title", "excerpt", "x_post"):
        if _contradicts(copy.get(field) or "", active):
            problems.append(f"the {field.replace('x_post', 'tweet')} calls an area quiet that has an incident")
    text = " ".join([copy.get("title", ""), copy.get("excerpt", ""), " ".join(copy.get("key_points") or []),
                     re.sub(r"<[^>]+>", " ", copy.get("article_html") or "")]).lower()
    for inc in included:
        name = (inc.get("vessel_name") or "").strip()
        if name and name.lower() not in text:
            problems.append(f"{name.title()} is in the data but not named in the article")
    for f in fixed:
        log.info("Consistency: %s", f)
    for pr in problems:
        log.warning("Consistency: %s", pr)
    return fixed, problems


def editor_notes(day: str) -> list[str]:
    """Notes from today's editor check (/review note: lines). They describe what the data cannot hold (a wrong
    credit, a detail in the wrong paragraph, conflicting dates), so the writer must follow them on the rebuild."""
    review = read_json(BRIEFS_DIR / f"{day}.json", {}).get("review") or {}
    if review.get("status") != "done":
        return []
    # "resend" lines are housekeeping for the workflow, not editorial notes
    return [str(n) for n in review.get("notes") or [] if str(n).strip()
            and not re.match(r"(automatic )?resend\b", str(n).strip(), re.I)]


def build(now=None, only_ids: set | None = None) -> dict:
    """only_ids: the rebuild after the editor check uses only the incidents the editor saw (plus any it
    separated), so nothing collected after the check slips in unchecked."""
    now = now or now_utc()
    since = now - timedelta(hours=int(env("BRIEF_WINDOW_HOURS", "24")))
    day_label = now.strftime("%-d %B %Y")
    incidents = store.load()
    new, updated, corrections = select(incidents, since)
    if only_ids is not None:
        dropped = [i["id"] for i in new + updated + corrections if i["id"] not in only_ids]
        if dropped:
            log.info("Frozen to the editor-checked incidents; left for tomorrow: %s", ", ".join(dropped))
        new, updated, corrections = ([i for i in x if i["id"] in only_ids] for x in (new, updated, corrections))
    from .writer import write

    # code plans the brief (lead, sections, context), the model writes the sentences (tracker/writer.py)
    copy = write(day_label, new, updated, corrections, incidents, now, editor_notes(now.date().isoformat()))
    copy["x_post"] = fit_tweet(copy["x_post"])
    copy["article_html"] = _clean_html(copy["article_html"])
    log.info("Plan: %s", copy.get("plan"))
    fixed, problems = enforce_consistency(copy, new + updated) if copy["article_html"] else ([], [])

    if copy["article_html"]:
        parts = [f'<p style="font-size:14px;color:{MUTED}">Reporting period: the 24 hours to '
                 f'{now.strftime("%H:%M")} UTC on {html.escape(day_label)}. By the iMariners Security Desk.</p>']
        if copy["key_points"]:
            parts.append(key_points_html(copy["key_points"]))
        parts.append(copy["article_html"])
    else:  # the AI failed: fall back to the structured layout
        parts = [f"<p>In the 24 hours to 06:00 UTC on {html.escape(day_label)}: "
                 f"{html.escape(copy['excerpt'])}</p>"]
        parts += [incident_html(i) for i in new + updated]
    if corrections:
        written = copy.get("correction_notes") or []
        if len(written) != len(corrections):
            log.warning("Corrections: %d written for %d items, using the plain wording", len(written), len(corrections))
        lines = written if len(written) == len(corrections) else [
            f"Correction to our {_day((i.get('published_in') or [''])[0])} brief: "
            f"{((i.get('verdict') or {}).get('note') or 'the report could not be confirmed and has been withdrawn.').rstrip('.')}."
            for i in corrections]
        parts.append("<h2>Corrections</h2>" + "".join(f"<p>{html.escape(c)}</p>" for c in lines))
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
            "fact_check": copy.get("fact_check", "not run"), "fact_check_fixes": copy.get("fact_check_fixes", []),
            "consistency_fixed": fixed, "consistency_problems": problems,
            "incident_ids": [i["id"] for i in new + updated], "correction_ids": [i["id"] for i in corrections],
            "counts": {"new": len(new), "updated": len(updated), "corrections": len(corrections)},
            "_incidents": new + updated}


def publish(brief: dict, image: Path) -> dict:
    from .wordpress import WordPress

    wp = WordPress()
    record_path = BRIEFS_DIR / f"{brief['date']}.json"
    record = read_json(record_path, {})
    mode = env("PUBLISH_MODE", "draft")
    if record.get("post_id"):
        try:  # a rebuild after the post went live must not take it offline
            if wp._req("GET", f"/posts/{record['post_id']}", params={"context": "edit"}).get("status") == "publish":
                mode = "publish"
        except RuntimeError as exc:
            log.warning("Could not read the current post status: %s", exc)
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
                  **{k: brief[k] for k in ("title", "excerpt", "x_post", "incident_ids", "correction_ids", "counts", "fact_check",
                                     "fact_check_fixes", "generated_at", "consistency_fixed", "consistency_problems")},
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
    # a new link on every rebuild (frozen rebuilds keep the morning's generated_at), so no cached copy is shown
    version = re.sub(r"\D", "", iso(now_utc()))[-6:]
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
    # "confirmed" must rest on Hermes's check or an official list, never on wording alone
    shaky = [i for i in used if i["status"] == "confirmed" and not i.get("verdict") and not has_official(i)]
    unchecked_single = [i for i in single if not i.get("verdict")]
    text = brief["html"] + brief["title"] + brief["x_post"]
    dashes = len(re.findall("[\u2014\u2013]", text))
    tweet_len = len(brief["x_post"]) + 24
    checks = {
        "dates": "ok" if not undated else f"{len(undated)} approximate",
        "attribution": "ok" if not unattributed else f"{len(unattributed)} claims without a named source",
        "official coverage": f"{len(covered)}/{len(official_recent)}" + (" ok" if len(covered) == len(official_recent) else " MISSING"),
        "verified": f"{len(verified)}/{len(used)}",
        "single-source items": str(len(single)) + (f", {len(unchecked_single)} without verification" if unchecked_single else ""),
        "confirmed": "ok" if not shaky else f"{len(shaky)} marked confirmed without proof",
        "fact-check": brief.get("fact_check", "not run"),
        "tweet": f"{tweet_len}/280" + (" ok" if tweet_len <= 280 else " TOO LONG"),
        "dashes": "ok" if not dashes else f"{dashes} found",
        "consistency": ("; ".join(brief.get("consistency_problems") or []) + " found") if brief.get("consistency_problems")
        else (f"ok ({len(brief['consistency_fixed'])} contradiction(s) removed)" if brief.get("consistency_fixed") else "ok"),
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
    from .review import summary_line

    payload = {**record, "needs_approval": record["status"] != "publish", "wp_url": env("WP_URL"),
               "quality": " ".join(x for x in (llm.balance_line(llm.balance_usd(), float(env("LOW_BALANCE_USD", "3"))),
                                               summary_line(record), record.get("quality", "")) if x)}
    headers = {"X-Tracker-Token": env("N8N_WEBHOOK_TOKEN", "")}
    # Retry a few times; if n8n still refuses, fail loudly so the brief is NOT marked as sent and the
    # watchdog or a backup run can send it once n8n is back (8 Oct 2026: n8n's database failed with a 500).
    last = ""
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            log.info("n8n webhook -> %s", resp.status_code)
            if resp.status_code < 300:
                return
            last = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}"
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"n8n did not accept the approval message ({last}); the brief was not sent")


def publish_now(day: str) -> None:
    """Publish a day's draft directly on WordPress: the fallback when n8n is down (owner asks Hermes on
    Telegram; Hermes comments '/publish <date>' on issue 38)."""
    from .wordpress import WordPress

    path = BRIEFS_DIR / f"{day}.json"
    record = read_json(path, {})
    if not record.get("post_id"):
        raise SystemExit(f"No brief record with a WordPress post for {day}")
    post = WordPress()._req("POST", f"/posts/{record['post_id']}", json={"status": "publish"})
    record.update(status=post.get("status"), link=post.get("link"), published_via="github", published_at=iso(now_utc()))
    write_json(path, record)
    log.info("Published post %s: %s", record["post_id"], post.get("link"))


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
    ap.add_argument("--notify-if-pending", action="store_true", help="send today's brief only if not yet sent")
    ap.add_argument("--refresh-image", metavar="YYYY-MM-DD", help="redraw the map of a published brief and swap it in")
    ap.add_argument("--reviewed", action="store_true",
                    help="rebuild after the editor check: same reporting time, only the incidents the editor saw")
    ap.add_argument("--publish-now", metavar="YYYY-MM-DD", help="publish that day's draft on WordPress (no n8n needed)")
    args = ap.parse_args()

    if args.publish_now:
        publish_now(args.publish_now)
        return

    if args.refresh_image:
        refresh_image(args.refresh_image)
        return

    if args.notify or args.notify_if_pending:
        path = BRIEFS_DIR / f"{now_utc().date().isoformat()}.json"
        record = read_json(path, {})
        if not record.get("post_id"):
            log.info("No brief published today; nothing to send to n8n")
        elif args.notify_if_pending and record.get("notified"):
            log.info("Today's brief was already sent for approval")
        else:
            notify_n8n(record)
            record["notified"] = iso(now_utc())
            write_json(path, record)
        return

    now, only = None, None
    if args.reviewed:
        from .review import REVIEW_DIR

        day = now_utc().date().isoformat()
        record = read_json(BRIEFS_DIR / f"{day}.json", {})
        request = read_json(REVIEW_DIR / f"{day}.json", {})
        if request.get("incidents"):
            only = {i["id"] for i in request["incidents"]} | set((record.get("review") or {}).get("restored") or [])
        now = parse_dt(record.get("generated_at")) or None
    brief = build(now, only)
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
    from .review import write_request

    write_request(brief["date"], record)
    incidents = store.load()
    for inc in incidents:
        if inc["id"] in brief["incident_ids"] and brief["date"] not in inc.get("published_in", []):
            inc.setdefault("published_in", []).append(brief["date"])
    store.save(incidents)
    if env("NOTIFY_LATER") != "1":  # the workflow notifies after the preview page is online
        notify_n8n(record)


if __name__ == "__main__":
    main()

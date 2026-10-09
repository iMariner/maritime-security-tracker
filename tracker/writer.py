"""Writes the brief in two layers.

Code decides the structure: which incidents are new attacks, real updates or older attacks first reported now;
which story leads (the most serious new attack); the order of the area sections; the quiet areas; the seven-day
context sentence; the crew section. These are decisions a cheap model gets wrong now and then, so the model
never makes them.

The model only writes sentences for named slots (headline, standfirst, lede, one paragraph per incident, key
points for the incidents code picked, tweet, correction lines). A second pass fact-checks those slots. Code then
assembles the article, so a slot can never move, repeat or vanish.
"""
from __future__ import annotations

import html
import json
import re
from datetime import timedelta

from . import lessons, llm
from .common import log, no_em_dash, now_utc, parse_dt

AREAS = {"Strait of Hormuz and the Gulf": {"Strait of Hormuz", "Persian Gulf", "Gulf of Oman"},
         "Red Sea and Gulf of Aden": {"Red Sea", "Gulf of Aden"}, "Black Sea": {"Black Sea", "Sea of Azov"}}
AREA_IN_TEXT = {"Strait of Hormuz and the Gulf": "the Strait of Hormuz and the Gulf",
                "Red Sea and Gulf of Aden": "the Red Sea and Gulf of Aden", "Black Sea": "the Black Sea"}
STATUS_RANK = {"confirmed": 2, "reported": 1, "claimed": 0}
CREW_LINE = ("Report any attack or suspicious approach to UKMTO, and follow UKMTO and JMIC advisories and company "
             "security instructions.")


def area_of(inc: dict) -> str | None:
    return next((a for a, regions in AREAS.items() if inc.get("region") in regions), None)


def _text(inc: dict, *keys) -> str:
    return " ".join(str(inc.get(k) or "") for k in keys)


def hurt(inc: dict) -> bool:
    """Someone killed, injured or missing (the casualties field, not denied)."""
    c = str(inc.get("casualties") or "")
    return bool(re.search(r"kill|dead|died|injur|wound|missing|casualt", c, re.I)
                and not re.search(r"\bno (one|injur|casualt|death)|unharmed|\ball (crew )?safe", c, re.I))


def severity(inc: dict) -> float:
    """News value for choosing the lead: deaths, sinking or missing crew first, then injuries, then damage."""
    cas = str(inc.get("casualties") or "")
    dmg = _text(inc, "damage", "summary")
    if hurt(inc) and re.search(r"kill|dead|died|missing", cas, re.I) or re.search(r"\bsank\b|\bsunk\b|sinking", dmg, re.I):
        score = 5.0
    elif hurt(inc):
        score = 4.0
    elif re.search(r"fire|ablaze|damag|hole|explosion|struck|hit by", dmg, re.I):
        score = 3.0
    else:
        score = 2.0
    status = inc.get("status") or "reported"
    score += {"confirmed": 0.5, "reported": 0.2, "claimed": -1.5}.get(status, 0)
    if inc.get("vessel_name"):
        score += 0.1
    return score


def plan(new: list, updated: list, corrections: list, incidents: list, now) -> dict:
    """The structure of the brief, decided in code."""
    cut48 = now - timedelta(hours=48)
    fresh = [i for i in new if (d := parse_dt(i.get("date_utc"))) is None or d >= cut48 or hurt(i)]
    earlier = [i for i in new if i not in fresh]
    by_score = lambda xs: sorted(xs, key=lambda i: (-severity(i), -(parse_dt(i.get("date_utc")) or now).timestamp()))
    fresh, updated, earlier = by_score(fresh), by_score(updated), by_score(earlier)
    lead = fresh[0] if fresh else (updated[0] if updated else None)
    lead_kind = "new" if fresh else ("update" if updated else None)

    sections = []
    for area in AREAS:
        items = [("new", i) for i in fresh if area_of(i) == area] + [("update", i) for i in updated if area_of(i) == area] \
            + [("earlier", i) for i in earlier if area_of(i) == area]
        if items:
            top = max(severity(i) for _, i in items)
            sections.append({"area": area, "items": items, "top": top,
                             "has_lead": any(i is lead for _, i in items)})
    sections.sort(key=lambda s: (not s["has_lead"], -s["top"]))
    quiet = [a for a in AREAS if a not in {s["area"] for s in sections}]
    # key points: the lead, then other new attacks, then updates (never older attacks), at most 4
    point_ids = [i["id"] for i in ([lead] if lead else []) + [i for i in fresh if i is not lead] + updated][:4]
    return {"fresh": fresh, "updated": updated, "earlier": earlier, "corrections": corrections, "lead": lead,
            "lead_kind": lead_kind, "sections": sections, "quiet": quiet, "point_ids": point_ids,
            "context": context_sentence(incidents, now, [s["area"] for s in sections])}


def context_sentence(incidents: list, now, areas: list[str]) -> str:
    """Seven-day counts from our own data, written by code, given once (second paragraph)."""
    parts = []
    for area in areas:
        regions = AREAS[area]
        hits = [d for i in incidents if i.get("region") in regions and i.get("status") in ("confirmed", "reported")
                and not i.get("merged_into") and i.get("vessel_category") != "naval"
                and any(i.get(k) for k in ("vessel_name", "imo", "flag", "vessel_type"))
                and (d := parse_dt(i.get("date_utc")))]
        week = sum(1 for d in hits if now - timedelta(days=7) <= d <= now)
        before = sum(1 for d in hits if now - timedelta(days=14) <= d < now - timedelta(days=7))
        if week or before:
            parts.append(f"{week} in {AREA_IN_TEXT[area]} ({before} the week before)")
    if not parts:
        return ""
    return ("Merchant ships reported hit in the last seven days, according to the iMariners tracker: "
            + "; ".join(parts) + ".")


def _facts(inc: dict, kind: str) -> dict:
    f = {k: inc.get(k) for k in ("vessel_name", "vessel_type", "flag", "date_utc", "location_text", "attack_type",
                                 "damage", "casualties", "attribution_claimed", "status", "official_source_cited",
                                 "summary", "position_note")}
    f["id"], f["kind"] = inc["id"], kind
    f["reported_by"] = sorted({s["source"] for s in inc["sources"] if s.get("source_type") != "satellite"})[:6]
    if inc.get("verdict"):
        f["checked_by_iMariners"] = inc["verdict"].get("note")
    return {k: v for k, v in f.items() if v not in (None, "", [])}


SYSTEM = """You write sentences for the iMariners daily maritime security brief, read by seafarers and ship managers.
Plain, calm British English, like Reuters or Lloyd's List. Use ONLY the facts given. Never add ships, numbers,
causes, quotes, advice or background. Never use em or en dashes.

The structure is already decided; you only fill these slots and return them as JSON:
"title": headline, at most 80 characters, sentence case, active voice, about the LEAD incident only, naming the
  ship when known. If lead_kind is "update", the headline says what is new (for example the ship was named or
  confirmed), not that the attack happened today.
"standfirst": one sentence, at most 30 words, adding detail beyond the headline (place, damage, crew).
"lede": one sentence, at most 35 words: who, what, where, when, and who said it, for the lead incident.
"paragraphs": an object with one entry per incident id given. kind "new": 2 or 3 short sentences (ship, flag and
  type, time and place, damage and crew, who said it, what is still unknown). For the lead, add what the lede did
  not say instead of repeating it. kind "update": 1 or 2 sentences saying what is new since our last brief and when
  the attack happened. kind "earlier": ONE sentence starting "Earlier in the week," with its date.
"key_points": an object with one entry per id in point_ids: one sentence of at most 18 words each, each a
  different fact, worded differently from the headline and lede.
"tweet": one or two sentences, at most 200 characters, about the lead incident, then 3 or 4 hashtags from
  #MaritimeSecurity #Shipping #Seafarers #BlackSea #StraitOfHormuz #RedSea #Tanker #UKMTO #MaritimeNews.
"correction_lines": one sentence per item in corrections: "Our <date> brief reported <what>; <what the check found>."

Rules for every slot: give the date of every attack ("on 7 October"). Credit each fact to who said it, once per
paragraph. "claimed" reads as one party's claim, never as fact; "reported" is independent reporting without
official confirmation; "confirmed" only names a neutral authority, the owner or the flag state. A ship name is
UKMTO's only if UKMTO named it. Ship names in normal capitalisation (Acers, not ACERS); no IMO numbers in the
headline. editor_notes come from the editor who checked the sources: where a note concerns an incident, follow it
in that incident's slots; notes win over the facts. Never mention the notes."""


def _ask(payload: dict) -> dict:
    system = SYSTEM + lessons.prompt_block("writing")
    return llm.chat_json(system, json.dumps(payload, ensure_ascii=False), kind="brief", max_tokens=3500)


def _fact_check(slots: dict, payload: dict) -> tuple[dict, list[str]]:
    system = ("You fact-check the slots of a maritime security brief against FACTS (incident records and editor notes). "
              "Correct any sentence the facts do not support: wrong date, wrong place, a claim written as fact, the "
              "wrong source credited, details from another incident, a ship or number not in the facts, an older attack "
              "presented as new. Keep every slot and every id, keep the style, never add facts, no em or en dashes. "
              'Return JSON {"slots": <the same shape as SLOTS>, "corrections": ["one short line per change"]}.')
    try:
        out = llm.chat_json(system, json.dumps({"FACTS": payload, "SLOTS": slots}, ensure_ascii=False),
                            kind="brief", max_tokens=3500)
    except (RuntimeError, ValueError) as exc:
        log.warning("Fact-check skipped: %s", exc)
        return slots, ["skipped"]
    fixed = out.get("slots") if isinstance(out.get("slots"), dict) else {}
    merged = dict(slots)
    for k, v in fixed.items():
        if k in slots and v:
            if isinstance(slots[k], dict) and isinstance(v, dict):
                merged[k] = {**slots[k], **{i: t for i, t in v.items() if i in slots[k] and str(t).strip()}}
            elif isinstance(slots[k], type(v)):
                merged[k] = v
    notes = [str(c) for c in out.get("corrections") or [] if str(c).strip()
             and not re.search(r"\bno (changes|corrections)\b|nothing (to|was) (change|correct)", str(c), re.I)]
    return merged, notes


def _fallback_sentence(inc: dict, kind: str) -> str:
    s = no_em_dash(str(inc.get("summary") or "")).strip()
    s = re.split(r"(?<=[.!?])\s+", s)[0] if s else f"A {inc.get('vessel_type') or 'ship'} was reported attacked."
    return ("Earlier in the week, " + s[0].lower() + s[1:]) if kind == "earlier" and not s.lower().startswith("earlier") else s


def _title_ok(title: str, lead: dict | None) -> bool:
    if not title or not lead:
        return bool(title)
    name = (lead.get("vessel_name") or "").lower()
    place = re.sub(r",.*$", "", str(lead.get("location_text") or "")).lower()
    words = [w for w in re.findall(r"[a-z]{4,}", place) if w not in ("about", "nautical", "miles", "north", "south",
                                                                     "east", "west", "near", "coast", "strait")]
    t = title.lower()
    return (name and name.split()[0] in t) or any(w in t for w in words) or (lead.get("region") or "").lower() in t


def write(day_label: str, new: list, updated: list, corrections: list, incidents: list, now,
          editor_notes: list | None = None) -> dict:
    """Returns the same fields build() used from the old writer: title, excerpt, key_points, article_html,
    x_post, correction_notes, fact_check, fact_check_fixes, quiet_areas, plus the plan."""
    now = now or now_utc()
    p = plan(new, updated, corrections, incidents, now)
    kinds = {i["id"]: k for s in p["sections"] for k, i in s["items"]}
    payload = {
        "date": day_label,
        "lead_kind": p["lead_kind"],
        "lead_id": p["lead"]["id"] if p["lead"] else None,
        "incidents": [_facts(i, kinds[i["id"]]) for s in p["sections"] for _, i in s["items"]],
        "point_ids": p["point_ids"],
        "editor_notes": list(editor_notes or []),
        "corrections": [{"first_published_in_brief_of": (i.get("published_in") or [None])[0],
                         "what_we_reported": i.get("summary"),
                         "why_it_was_wrong": (i.get("verdict") or {}).get("note")} for i in corrections],
    }
    slots, fixes = {}, []
    if p["lead"] or corrections:
        try:
            slots = _ask(payload)
        except RuntimeError as exc:
            log.warning("AI writer failed, using plain sentences: %s", exc)
        if slots:
            slots, fixes = _fact_check(slots, payload)
    paragraphs = slots.get("paragraphs") if isinstance(slots.get("paragraphs"), dict) else {}
    points = slots.get("key_points") if isinstance(slots.get("key_points"), dict) else {}

    clean = lambda s: no_em_dash(str(s or "")).strip()
    lead = p["lead"]
    title = clean(slots.get("title"))[:90]
    if not _title_ok(title, lead):
        who = (lead.get("vessel_name") or "").title() or (lead.get("vessel_type") or "Ship").capitalize() if lead else ""
        title = (f"{who} {'named' if p['lead_kind'] == 'update' else 'hit'} in {AREA_IN_TEXT[area_of(lead)]}"
                 if lead else f"No new attacks on merchant ships reported: {day_label}")
        log.warning("Headline did not cover the lead story; using: %s", title)

    body = []
    lede = clean(slots.get("lede")) or (_fallback_sentence(lead, "new") if lead else "")
    if lede:
        body.append(f"<p>{html.escape(lede)}</p>")
    if p["context"]:
        body.append(f"<p>{html.escape(p['context'])}</p>")
    for s in p["sections"]:
        body.append(f"<h2>{html.escape(s['area'])}</h2>")
        for kind, inc in s["items"]:
            text = clean(paragraphs.get(inc["id"])) or _fallback_sentence(inc, kind)
            if kind == "earlier" and not text.lower().startswith("earlier"):
                text = "Earlier in the week, " + text[0].lower() + text[1:]
            body.append(f"<p>{html.escape(text)}</p>")
    if p["quiet"]:
        names = [AREA_IN_TEXT[a] for a in p["quiet"]]
        joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]
        body.append(f"<p>No new attacks on merchant ships were reported in {joined} in the last 24 hours.</p>")
    body.append(f"<h2>What crews should know</h2><p>{html.escape(CREW_LINE)}</p>")

    key_points = [clean(points.get(i)) for i in p["point_ids"] if clean(points.get(i))]
    if p["quiet"]:
        names = [AREA_IN_TEXT[a] for a in p["quiet"]]
        key_points.append("No new attacks on merchant ships were reported in "
                          + (names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]) + ".")
    tweet = clean(slots.get("tweet")) or (f"{title}. #MaritimeSecurity #Shipping" if lead else "")
    lines = slots.get("correction_lines") if isinstance(slots.get("correction_lines"), list) else []
    return {
        "title": title or f"Maritime security brief: {day_label}",
        "excerpt": clean(slots.get("standfirst")) or lede or f"Attacks on merchant ships in the last 24 hours, {day_label}.",
        "key_points": key_points[:5],
        "article_html": "\n".join(body),
        "x_post": tweet,
        "correction_notes": [clean(c) for c in lines if clean(c)],
        "fact_check": "skipped" if fixes == ["skipped"] else (f"{len(fixes)} correction(s)" if fixes else "no corrections needed"),
        "fact_check_fixes": [] if fixes == ["skipped"] else [f[:300] for f in fixes],
        "quiet_areas": p["quiet"],
        "plan": {"lead_id": lead["id"] if lead else None, "lead_kind": p["lead_kind"],
                 "new": [i["id"] for i in p["fresh"]], "updates": [i["id"] for i in p["updated"]],
                 "earlier": [i["id"] for i in p["earlier"]]},
    }

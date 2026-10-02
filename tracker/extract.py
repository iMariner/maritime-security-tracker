"""AI step: decide which items report an attack on a vessel and extract structured incidents."""
from __future__ import annotations

import json

from datetime import timedelta

from . import incidents as store, llm
from .common import env, load_yaml, log, now_utc, parse_dt

FIELDS = """{
  "region": one of REGIONS,
  "vessel_name": "full name in Latin letters as registered, keeping numbers and suffixes (e.g. 'KAZIMAH III', 'NORDIC STAR 2'), or null if not named",
  "imo": "7 digit IMO number or null",
  "flag": "flag state or null",
  "vessel_type": "tanker | bulk carrier | general cargo | container | LNG/LPG carrier | ro-ro | passenger | tug | fishing | naval | other | null",
  "vessel_category": "merchant | naval | fishing | other",
  "date_utc": "ISO 8601 date-time of the attack (UTC) as best known; date only is fine",
  "location_text": "where, in English (e.g. 'Odesa port, Ukraine' or '40 nm east of Fujairah')",
  "lat": number or null, "lon": number or null (only if the text gives or clearly implies a position),
  "attack_type": "missile | drone (UAV) | sea drone (USV) | mine | boarding/seizure | gunfire | GNSS interference | suspicious approach | explosion (cause unknown) | other",
  "damage": "short English description or null",
  "casualties": "short English description (e.g. '2 crew injured') or null",
  "attribution_claimed": "ONLY if the item explicitly says who carried out or claimed the attack (e.g. 'Russia's defence ministry claimed it', 'Ukraine said it struck', 'the Houthis claimed'), that party in a few words; null if no one is named. Never infer it from context or 'framing'",
  "official_source_cited": "neutral authority quoted as confirming it (UKMTO, JMIC, MARAD, NATO Shipping Centre, a coast guard, flag state, ship owner or manager), or null",
  "summary": "2 sentences in plain English, facts only, attributing claims (e.g. 'Russia's defence ministry said ...')",
  "is_recap": true if the item only mentions an older attack in passing, otherwise false,
  "conflicting": true if the item disputes or contradicts another account, otherwise false,
  "independent_evidence": true only if the item gives evidence beyond one side's statement (eyewitnesses, crew,
    the owner or manager, port or coast guard, images, a neutral authority, or the other side confirming);
    false if it only repeats what one party (a ministry, army, navy, or government of Russia, Ukraine, Iran, etc.) said,
  "confidence": 0.0 to 1.0, how sure you are that a real attack on this vessel is being reported,
  "same_as": "id of a KNOWN incident that this is the same real-world attack as, or null if it is a new one",
  "event_key": "short label for the real-world event, identical for every report of the same attack in this request (e.g. 'kazimah-hormuz-0929')"
}"""


def _system_prompt() -> str:
    cfg = load_yaml("regions.yaml")
    regions = [r["name"] for r in cfg.get("regions", []) if r.get("enabled")]
    naval = "Include attacks on warships (vessel_category naval)." if cfg.get("include_naval") else (
        "Ignore attacks on warships and military boats; only civilian vessels count."
    )
    return f"""You are a maritime security analyst. You read news items and Telegram posts in English,
Ukrainian, Russian, Turkish, Romanian and Arabic, and extract reports of attacks on vessels.

In scope: a vessel attacked, struck, damaged, mined, seized, boarded or deliberately interfered with
(including vessels hit while in port) in these regions: {", ".join(regions)}. {naval}
Out of scope: strikes on ports or land with no vessel affected, general war news, military
statements without a specific vessel incident, piracy outside these regions.

Rules:
- Many outlets report the same attack. Compare every incident with the KNOWN incidents given to you
  (same region, vessel, date, location, attack). If it is the same attack, set "same_as" to that id.
  Several items in one request that describe the same attack must share one "event_key".
- A roundup that lists several earlier attacks describes each of them; date each one correctly.
- Use only facts in the item. Never invent names, IMO numbers, dates or positions; use null.
- Translate everything into English. Give vessel names in Latin letters.
- One item can describe several incidents (several vessels); list each separately.
- Party claims stay claims: if only one side says it happened, say so in the summary.
- Today is {now_utc().date().isoformat()}.

Return JSON: {{"items": [{{"item_id": "...", "incidents": [ ... ]}}]}}
List ONLY items that contain at least one in-scope incident; leave every other item out.
If no item qualifies, return {{"items": []}}. Return the JSON object only, no other text.
Each incident has these fields:
{FIELDS.replace("REGIONS", json.dumps(regions))}"""


def _known(incidents: list[dict]) -> list[dict]:
    """Compact list of recent open incidents the model can match new reports against."""
    cutoff = now_utc() - timedelta(days=4)
    recent = [i for i in incidents if i.get("status") != "rejected"
              and (parse_dt(i.get("date_utc")) or parse_dt(i.get("first_seen")) or now_utc()) >= cutoff]
    recent.sort(key=lambda i: i.get("last_updated") or "", reverse=True)
    return [{"id": i["id"], "region": i.get("region"), "date": (i.get("date_utc") or "")[:10],
             "vessel": i.get("vessel_name"), "type": i.get("vessel_type"), "attack": i.get("attack_type"),
             "where": i.get("location_text"), "summary": (i.get("summary") or "")[:160]} for i in recent[:40]]


def extract(items: list[dict], incidents: list[dict]) -> tuple[int, int, set, int]:
    """Read items with the AI and merge what it finds into `incidents`, one batch at a time,
    so each batch is matched against everything found before it.

    Returns (new incidents, merged reports, ids of items the AI read, failed batches).
    A failed batch is skipped; its items stay unread and are retried on the next run.
    """
    # GitHub Models' free tier caps each request at about 8k input tokens, so send less per call there.
    batch_size, max_chars = (4, 1500) if llm.free_tier_only() else (8, 3000)
    batch_size = int(env("EXTRACT_BATCH_SIZE") or batch_size)
    system = _system_prompt()
    by_id = {it["id"]: it for it in items}
    new = merged = failed = 0
    done: set = set()
    events: dict = {}  # event_key -> incident id, for reports of one event within this run
    total = (len(items) + batch_size - 1) // batch_size
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        payload = {
            "known_incidents": _known(incidents),
            "items": [{"item_id": it["id"], "source": it["source"], "published_at": it["published_at"],
                       "title": it["title"], "text": it["text"][:max_chars]} for it in batch],
        }
        try:
            data = llm.chat_json(system, json.dumps(payload, ensure_ascii=False), max_tokens=8000)
        except RuntimeError as exc:
            failed += 1
            log.warning("Extract: batch %d/%d skipped, will retry next run: %s", i // batch_size + 1, total, str(exc)[:300])
            continue
        done.update(it["id"] for it in batch)
        for entry in data.get("items", []):
            src = by_id.get(entry.get("item_id"))
            if not src:
                continue
            for rep in entry.get("incidents") or []:
                if rep.get("is_recap"):
                    continue
                rep["source"] = {
                    "url": src["url"], "source": src["source"], "source_type": src["source_type"],
                    "side": src["side"], "kind": src["kind"], "published_at": src["published_at"],
                    "title": src.get("title") or None,
                }
                key = (rep.get("event_key") or "").strip().lower()
                if not rep.get("same_as") and key in events:
                    rep["same_as"] = events[key]
                inc, is_new = store.merge(rep, incidents, model_checked=True)
                if key:
                    events[key] = inc["id"]
                new += is_new
                merged += not is_new
        log.info("Extract: batch %d/%d done", i // batch_size + 1, total)
    log.info("Extract: %d new incidents, %d reports merged, %d items read, %d batches failed", new, merged, len(done), failed)
    return new, merged, done, failed

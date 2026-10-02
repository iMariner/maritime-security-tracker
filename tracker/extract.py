"""AI step: decide which items report an attack on a vessel and extract structured incidents."""
from __future__ import annotations

import json

from . import llm
from .common import load_yaml, log, now_utc

FIELDS = """{
  "region": one of REGIONS,
  "vessel_name": "name in Latin letters as registered (e.g. 'KAIROS'), or null if not named",
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
  "attribution_claimed": "who is said or claimed to be responsible, or null",
  "official_source_cited": "neutral authority quoted as confirming it (UKMTO, JMIC, MARAD, NATO Shipping Centre, a coast guard, flag state, ship owner or manager), or null",
  "summary": "2 sentences in plain English, facts only, attributing claims (e.g. 'Russia's defence ministry said ...')",
  "is_recap": true if the item only mentions an older attack in passing, otherwise false,
  "conflicting": true if the item disputes or contradicts another account, otherwise false,
  "confidence": 0.0 to 1.0, how sure you are that a real attack on this vessel is being reported
}"""


def _system_prompt() -> str:
    cfg = load_yaml("regions.yaml")
    regions = [r["name"] for r in cfg.get("regions", []) if r.get("enabled")]
    naval = "Include attacks on warships (vessel_category naval)." if cfg.get("include_naval") else (
        "Ignore attacks on warships and military boats; only civilian vessels count."
    )
    return f"""You are a maritime security analyst. You read news items and Telegram posts in English,
Ukrainian, Russian, Turkish and Romanian, and extract reports of attacks on vessels.

In scope: a vessel attacked, struck, damaged, mined, seized, boarded or deliberately interfered with
(including vessels hit while in port) in these regions: {", ".join(regions)}. {naval}
Out of scope: strikes on ports or land with no vessel affected, general war news, military
statements without a specific vessel incident, piracy outside these regions.

Rules:
- Use only facts in the item. Never invent names, IMO numbers, dates or positions; use null.
- Translate everything into English. Give vessel names in Latin letters.
- One item can describe several incidents (several vessels); list each separately.
- Party claims stay claims: if only one side says it happened, say so in the summary.
- Today is {now_utc().date().isoformat()}.

Return JSON: {{"items": [{{"item_id": "...", "incidents": [ ... ]}}]}}
Each incident has these fields:
{FIELDS.replace("REGIONS", json.dumps(regions))}
Items with no in-scope incident get "incidents": []."""


def extract(items: list[dict]) -> list[dict]:
    """Return incident candidates, each with the item it came from attached as `source`."""
    # GitHub Models' free tier caps each request at about 8k input tokens, so send less per call there.
    batch_size, max_chars = (4, 1500) if llm.free_tier_only() else (8, 3000)
    system = _system_prompt()
    by_id = {it["id"]: it for it in items}
    results = []
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        payload = [
            {"item_id": it["id"], "source": it["source"], "published_at": it["published_at"],
             "title": it["title"], "text": it["text"][:max_chars]}
            for it in batch
        ]
        data = llm.chat_json(system, json.dumps({"items": payload}, ensure_ascii=False))
        for entry in data.get("items", []):
            src = by_id.get(entry.get("item_id"))
            if not src:
                continue
            for inc in entry.get("incidents") or []:
                if inc.get("is_recap"):
                    continue
                inc["source"] = {
                    "url": src["url"], "source": src["source"], "source_type": src["source_type"],
                    "side": src["side"], "kind": src["kind"], "published_at": src["published_at"],
                    "title": src.get("title") or None,
                }
                results.append(inc)
        log.info("Extract: batch %d/%d done", i // batch_size + 1, (len(items) + batch_size - 1) // batch_size)
    log.info("Extract: %d incident reports from %d items", len(results), len(items))
    return results

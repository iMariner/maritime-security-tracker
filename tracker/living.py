"""Separate evidence-reviewed public export; never mutates incident/news data.

Only an explicit, complete verification overlay can publish a record. This module
checks review structure, not factual truth. Independent reviewers must read the
underlying sources. Original corpus summaries, casualty prose, and news history
are never published through this export. Run python -m tracker.living.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = {"claimed", "reported", "confirmed"}
REGIONS = {"black sea": "Black Sea", "red sea": "Red Sea", "strait of hormuz": "Strait of Hormuz",
           "sea of azov": "Black Sea", "gulf of aden": "Red Sea", "hormuz": "Strait of Hormuz", "gulf of oman": "Strait of Hormuz", "persian gulf": "Strait of Hormuz"}


def safe_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"https", "http"} and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


def sources(value):
    result = []
    for item in value if isinstance(value, list) else []:
        item = {"url": item} if isinstance(item, str) else item
        if isinstance(item, dict) and safe_url(item.get("url")):
            result.append({"url": item["url"], "source": str(item.get("source") or "Source"),
                           **{key: item[key] for key in ("title", "published_at", "source_type", "kind") if isinstance(item.get(key), str)}})
    return result


def count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def casualties(value):
    unknown = {"status": "unknown", "deaths": None, "nationalities": [], "sources": []}
    if not isinstance(value, dict):
        return unknown
    refs = sources(value.get("sources"))
    if value.get("status") != "confirmed" or not count(value.get("deaths")) or not refs:
        return unknown
    nationalities = []
    for item in value.get("nationalities", []) if isinstance(value.get("nationalities"), list) else []:
        if not isinstance(item, dict):
            continue
        refs_n = sources(item.get("sources"))
        name = item.get("nationality")
        if item.get("status") == "confirmed" and isinstance(name, str) and name.strip() and count(item.get("deaths")) and refs_n:
            nationalities.append({"nationality": name.strip(), "deaths": item["deaths"], "status": "confirmed", "sources": refs_n})
    # An internally inconsistent nationality breakdown cannot support totals.
    if sum(item["deaths"] for item in nationalities) > value["deaths"]:
        nationalities = []
    return {"status": "confirmed", "deaths": value["deaths"], "nationalities": nationalities, "sources": refs, **({"minimum": True} if value.get("minimum") is True else {})}


def updates(value):
    result = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        at = item.get("at")
        try:
            if "T" not in at or datetime.fromisoformat(at.replace("Z", "+00:00")).tzinfo is None:
                continue
        except (TypeError, ValueError, AttributeError):
            continue
        refs = sources(item.get("sources"))
        if refs and item["text"].strip():
            result.append({"at": at, "text": item["text"].strip(), "sources": refs})
    return sorted(result, key=lambda item: datetime.fromisoformat(item["at"].replace("Z", "+00:00")), reverse=True)


def latest_update(incident):
    """Reuse the persisted Hermes news update only when its cited source is traceable.

    review.apply stamps its appended evidence source and news_changed_at together.
    A news_changed_at alone also represents vessel renaming, so it is not history.
    Older sources are not assumed to support later assertions.
    """
    at, text = incident.get("news_changed_at"), incident.get("latest_news")
    refs = [source for source in sources(incident.get("sources"))
            if source.get("published_at") == at]
    return updates([{"at": at, "text": text, "sources": refs}])


def verification(value):
    """Validate a review assertion, not the truth of its underlying claims."""
    if not isinstance(value, dict) or value.get("status") != "verified":
        raise ValueError("Verified independent review required")
    if set(value) - {"status", "checked_at", "sources", "vessel_name", "date_utc", "vessel_type", "summary", "imo", "region", "location_text", "attack_type", "date_note"}:
        raise ValueError("Unsupported verification fields")
    for key in ("vessel_name", "vessel_type", "summary"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError("Reviewed identity, type and summary required")
    if re.search(r"\b(unknown|unnamed|unidentified|unspecified)\b", value["vessel_name"], re.I):
        raise ValueError("Identified vessel required")
    try:
        stamp = datetime.fromisoformat(value["checked_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None or "T" not in value["checked_at"]:
            raise ValueError()
        datetime.strptime(value["date_utc"], "%Y-%m-%d")
        if len(value["date_utc"]) != 10:
            raise ValueError()
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ValueError("Timezone-aware review timestamp and exact attack date required") from None
    refs = value.get("sources")
    if not isinstance(refs, list) or not refs or any(not isinstance(r, dict) or not safe_url(r.get("url")) or not isinstance(r.get("source"), str) or not r["source"].strip() for r in refs):
        raise ValueError("Named linked review sources required")
    for key in ("location_text", "attack_type", "date_note"):
        if key in value and (not isinstance(value[key], str) or not value[key].strip()):
            raise ValueError("Invalid reviewed descriptive field")
    if "region" in value and str(value["region"]).strip().lower() not in REGIONS:
        raise ValueError("Unsupported reviewed region")
    if "imo" in value:
        imo = str(value["imo"])
        if not re.fullmatch(r"\d{7}", imo) or sum(int(n)*w for n,w in zip(imo[:6], range(7,1,-1))) % 10 != int(imo[-1]):
            raise ValueError("Invalid reviewed IMO")
    return deepcopy(value)


def export(incidents, overlay=None, history=None):
    """Export current and historical candidates through the same review gate.

    History is a separate array of incident stubs, never input to the news
    pipeline. Existing corpus IDs take precedence over historical stubs; reviewed
    vessel/date and IMO/date identities additionally deduplicate across both.
    """
    overlay = overlay or {"schema_version": 1, "incidents": {}}
    if overlay.get("schema_version") != 1 or not isinstance(overlay.get("incidents"), dict):
        raise ValueError("Unsupported living evidence schema")
    if history is None:
        history = []
    if not isinstance(history, list) or any(not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip() for item in history):
        raise ValueError("Historical candidates must be an array of incident objects with IDs")
    candidates = list(incidents)
    corpus_ids = {item.get("id") for item in candidates}
    historical_ids = set()
    for item in history:
        if item["id"] not in corpus_ids and item["id"] not in historical_ids:
            candidates.append(item)
            historical_ids.add(item["id"])
    result, awaiting, excluded = [], 0, 0
    seen = set()
    for original in candidates:
        evidence = overlay["incidents"].get(original.get("id"), {})
        if not isinstance(evidence, dict):
            raise ValueError("Incident evidence must be an object")
        review = None
        if "verification" in evidence:
            try:
                review = verification(evidence["verification"])
            except ValueError:
                pass
        region = str((review or {}).get("region", original.get("region")) or "").strip().lower()
        kind = str((review or {}).get("vessel_type", original.get("vessel_type")) or "")
        if original.get("status") not in PUBLIC or region not in REGIONS or re.search(r"\b(military|naval|warship|destroyer|frigate|corvette|submarine)\b", str(original.get("vessel_category") or "") + " " + kind, re.I):
            excluded += 1
            continue
        if review is None:
            awaiting += 1
            continue
        identity = re.sub(r"[^a-z0-9]", "", review["vessel_name"].lower())
        event_keys = {(identity, review["date_utc"])}
        if review.get("imo"):
            event_keys.add((str(review["imo"]), review["date_utc"]))
        if event_keys & seen:
            excluded += 1
            continue
        seen.update(event_keys)
        item = {"id": original["id"], "status": "verified", "region": REGIONS[region], "region_group": REGIONS[region],
                "vessel_name": review["vessel_name"].strip(), "vessel_type": review["vessel_type"].strip(),
                "date_utc": review["date_utc"], "summary": review["summary"].strip(), "latest_news": review["summary"].strip(),
                "verification": review, "sources": sources(review["sources"]),
                "casualties": casualties(evidence.get("casualties")), "updates": updates(evidence.get("updates"))}
        item["last_updated"] = max([review["checked_at"]] + [u["at"] for u in item["updates"]], key=lambda stamp: datetime.fromisoformat(stamp.replace("Z", "+00:00")))
        for key in ("location_text", "attack_type", "date_note"):
            if key in review:
                item[key] = review[key]
        if "imo" in review:
            item["imo"] = str(review["imo"])
        image = evidence.get("image")
        item["image"] = image if isinstance(image, dict) and safe_url(image.get("url")) and safe_url(image.get("source_url")) and image.get("credit") and image.get("alt") else None
        result.append(item)
    result.sort(key=lambda item: (item["date_utc"], item["id"]), reverse=True)
    return {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
            "review": {"reviewed_count": len(result), "awaiting_review_count": awaiting, "excluded_count": excluded,
                       "historical_candidate_count": len(historical_ids)},
            "methodology": {"coverage": ["Black Sea", "Red Sea", "Strait of Hormuz"], "count_label": "Reviewed incident records",
              "verification_policy": "Only identified vessels with recorded independent source review are public. Validation checks structure, not factual truth.",
              "counting_note": "Totals describe distinct reviewed vessel/date records, not all attacks. Same vessel/date duplicates are withheld; repeat attacks may be merged.",
              "casualty_policy": "Only explicitly confirmed sourced counts are included; unknown is not zero.",
              "coverage_note": "Historical collection, reporting and review are incomplete; these are not comprehensive war totals. Unreviewed records are withheld. Black Sea includes Sea of Azov; Red Sea includes Gulf of Aden; Hormuz includes adjacent Gulf of Oman and Persian Gulf reports.",
              "history_note": "Only overlay updates are displayed; historical news text is withheld."}, "incidents": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incidents", type=Path, default=ROOT / "data/incidents.json")
    parser.add_argument("--evidence", type=Path, default=ROOT / "data/living-evidence.json")
    parser.add_argument("--history", type=Path, default=ROOT / "data/living-history.json", help="Separate historical candidate array (optional)")
    parser.add_argument("--output", type=Path, default=ROOT / "out/living-incidents.json")
    args = parser.parse_args()
    overlay = json.loads(args.evidence.read_text()) if args.evidence.exists() else None
    history = json.loads(args.history.read_text()) if args.history.exists() else None
    payload = export(json.loads(args.incidents.read_text()), overlay, history)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()

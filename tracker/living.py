"""Additive public evidence export; never mutates incidents or the news pipeline.

Run ``python -m tracker.living --output _site/living-incidents.json``.
Hermes/reviewers may propose edits to data/living-evidence.json, keyed by existing
incident ID, for human review before committing. Example entry::

  {"casualties": {"status": "confirmed", "deaths": 1,
    "sources": [{"url": "https://authority.example/report", "source": "Authority"}],
    "nationalities": [{"nationality": "Indian", "deaths": 1,
      "status": "confirmed", "sources": [{"url": "https://authority.example/report"}]}]},
   "updates": [{"at": "2026-10-21T12:00:00Z", "text": "Death confirmed",
     "sources": [{"url": "https://authority.example/report"}]}]}

Top-level format: {"schema_version": 1, "incidents": {"INC-id": entry}}.
Only explicit confirmed, sourced numeric claims become totals. Free-text casualty
reports remain visible as context but never become numeric facts. Images require
url, source_url, credit and alt; adding them asserts permission to publish. This
module cannot verify rights. Unknown counts are null, including when reports say
nothing about casualties. Update histories must be supplied; none are invented.
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
           "hormuz": "Strait of Hormuz", "gulf of oman": "Strait of Hormuz", "persian gulf": "Strait of Hormuz"}


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
    return {"status": "confirmed", "deaths": value["deaths"], "nationalities": nationalities, "sources": refs}


def updates(value):
    result = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        at = item.get("at")
        try:
            datetime.fromisoformat(at.replace("Z", "+00:00"))
        except (TypeError, ValueError, AttributeError):
            continue
        refs = sources(item.get("sources"))
        if refs and item["text"].strip():
            result.append({"at": at, "text": item["text"].strip(), "sources": refs})
    return sorted(result, key=lambda item: item["at"], reverse=True)


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


def export(incidents, overlay=None):
    overlay = overlay or {"schema_version": 1, "incidents": {}}
    if overlay.get("schema_version") != 1 or not isinstance(overlay.get("incidents"), dict):
        raise ValueError("Unsupported living evidence schema")
    result = []
    for original in incidents:
        if original.get("status") not in PUBLIC or str(original.get("region") or "").strip().lower() not in REGIONS:
            continue
        category = str(original.get("vessel_category") or "").lower()
        vessel_type = str(original.get("vessel_type") or "").lower()
        if re.search(r"\b(military|naval|warship|destroyer|frigate|corvette|submarine)\b", category + " " + vessel_type):
            continue
        item = deepcopy(original)
        item["region_group"] = REGIONS[str(original["region"]).strip().lower()]
        evidence = overlay["incidents"].get(item.get("id"), {})
        if not isinstance(evidence, dict):
            raise ValueError("Incident evidence must be an object")
        item["casualties_text"] = original.get("casualties") if isinstance(original.get("casualties"), str) else None
        item["casualties"] = casualties(evidence.get("casualties", original.get("casualties")))
        item["sources"] = sources(original.get("sources"))
        item["updates"] = updates(original.get("updates")) + latest_update(original) + updates(evidence.get("updates"))
        item["updates"] = sorted(item["updates"], key=lambda update: update["at"], reverse=True)
        image = evidence.get("image")
        item["image"] = image if isinstance(image, dict) and safe_url(image.get("url")) and safe_url(image.get("source_url")) and image.get("credit") and image.get("alt") else None
        result.append(item)
    result.sort(key=lambda item: (str(item.get("date_utc") or ""), str(item.get("id") or "")), reverse=True)
    return {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
            "methodology": {"coverage": ["Black Sea", "Red Sea", "Strait of Hormuz"],
              "count_label": "Documented incident records",
              "counting_note": "Existing matching groups reports by vessel identity; repeat attacks may be merged. Record totals are not a complete count of distinct attacks.", "casualty_policy": "Only explicitly confirmed counts with supporting sources are included; unknown is not zero.",
              "coverage_note": "Available reporting is incomplete. Actual totals may be higher.",
              "history_note": "Updates reuse sourced, dated latest-news entries and supplied evidence history; earlier changes are not reconstructed."}, "incidents": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incidents", type=Path, default=ROOT / "data/incidents.json")
    parser.add_argument("--evidence", type=Path, default=ROOT / "data/living-evidence.json")
    parser.add_argument("--output", type=Path, default=ROOT / "out/living-incidents.json")
    args = parser.parse_args()
    overlay = json.loads(args.evidence.read_text()) if args.evidence.exists() else None
    payload = export(json.loads(args.incidents.read_text()), overlay)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()

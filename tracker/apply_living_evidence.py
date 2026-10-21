"""Apply authorised /evidence JSON comments to the additive living tracker overlay."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re

from . import living
from .common import ROOT, read_json, write_json

ALLOWED = {"OWNER", "MEMBER", "COLLABORATOR"}


def parse(body):
    if not isinstance(body, str) or not body.startswith("/evidence\n"):
        raise ValueError("Expected /evidence followed by JSON on a new line")
    raw = body.split("\n", 1)[1].strip()
    if raw.startswith("```json\n") and raw.endswith("```"):
        raw = raw[8:-3].strip()
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError("Evidence must be valid JSON") from None
    if not isinstance(value, dict) or set(value) - {"incident_id", "historical", "casualties", "update", "image", "verification"}:
        raise ValueError("Unsupported evidence fields")
    return value


def prepare_candidate(value, incidents):
    """Derive a new additive stub; existing corpus publication states prevail."""
    if "historical" in value and not isinstance(value["historical"], bool):
        raise ValueError("Historical must be a boolean")
    incident_id = value.get("incident_id")
    if isinstance(incident_id, str) and incident_id in {item.get("id") for item in incidents}:
        return None
    if value.get("historical") is not True:
        return None
    if not isinstance(incident_id, str) or not re.fullmatch(r"HIST-[A-Za-z0-9][A-Za-z0-9_-]{0,95}", incident_id):
        raise ValueError("New historical incidents require a valid HIST- ID")
    review = living.verification(value.get("verification"))
    region = review.get("region", "").strip().lower()
    if region not in living.REGIONS:
        raise ValueError("New historical incidents require a supported reviewed region")
    return {"id": incident_id, "status": "reported", "vessel_category": "merchant",
            "region": living.REGIONS[region], "vessel_type": review["vessel_type"]}


def validate(value, incidents):
    incident_id = value.get("incident_id")
    if not isinstance(incident_id, str) or incident_id not in {i.get("id") for i in incidents}:
        raise ValueError("Unknown incident ID")
    if "verification" in value and value["verification"] is not None:
        living.verification(value["verification"])
        original = next(i for i in incidents if i.get("id") == incident_id)
        if original.get("status") not in living.PUBLIC:
            raise ValueError("Cannot verify nonpublic, merged or rejected incidents")
    update = value.get("update")
    if not isinstance(update, dict) or set(update) - {"at", "text", "sources"} or len(living.updates([update])) != 1:
        raise ValueError("A dated, sourced update is required")
    if not isinstance(update.get("sources"), list) or len(living.sources(update["sources"])) != len(update["sources"]):
        raise ValueError("All update sources must be valid HTTP URLs")
    if "casualties" in value:
        claim = value["casualties"]
        if not isinstance(claim, dict) or set(claim) - {"status", "deaths", "sources", "nationalities", "minimum"}:
            raise ValueError("Invalid casualty evidence")
        if "minimum" in claim and not isinstance(claim["minimum"], bool):
            raise ValueError("Casualty minimum must be a boolean")
        if claim.get("status") == "unknown":
            if claim.get("deaths") is not None or claim.get("nationalities"):
                raise ValueError("Unknown casualties cannot contain counts")
        else:
            checked = living.casualties(claim)
            if checked["status"] != "confirmed":
                raise ValueError("Confirmed casualties need a nonnegative integer and sources")
            nationalities = claim.get("nationalities", [])
            if not isinstance(nationalities, list) or len(checked["nationalities"]) != len(nationalities):
                raise ValueError("Invalid or inconsistent nationality breakdown")
            for refs in [claim.get("sources", [])] + [n.get("sources", []) for n in nationalities]:
                if not isinstance(refs, list) or len(living.sources(refs)) != len(refs):
                    raise ValueError("Invalid casualty source")
    if "image" in value and value["image"] is not None:
        image = value["image"]
        if not isinstance(image, dict) or set(image) - {"url", "source_url", "credit", "alt"}:
            raise ValueError("Invalid image evidence")
        if not all(living.safe_url(image.get(k)) for k in ("url", "source_url")) or not all(isinstance(image.get(k), str) and image[k].strip() for k in ("credit", "alt")):
            raise ValueError("Image needs valid URLs, credit and alt text")
    return value


def apply_event(event, overlay, incidents):
    comment = event.get("comment", {})
    if event.get("action") != "created" or "pull_request" in event.get("issue", {}) or comment.get("author_association") not in ALLOWED:
        raise ValueError("Only trusted issue comments can apply evidence")
    comment_id = comment.get("id")
    if not isinstance(comment_id, int) or isinstance(comment_id, bool):
        raise ValueError("Missing comment identity")
    if overlay.get("schema_version") != 1 or not isinstance(overlay.get("incidents"), dict):
        raise ValueError("Unsupported living evidence schema")
    if any(a.get("comment_id") == comment_id for a in overlay.get("audit", [])):
        return deepcopy(overlay)
    value = parse(comment.get("body"))
    candidate = prepare_candidate(value, incidents)
    candidates = [*incidents, candidate] if candidate is not None else incidents
    value = validate(value, candidates)
    result = deepcopy(overlay)
    entry = result["incidents"].setdefault(value["incident_id"], {})
    before = deepcopy(entry)
    for key in ("casualties", "image", "verification"):
        if key in value:
            entry[key] = deepcopy(value[key])
    entry.setdefault("updates", []).append(deepcopy(value["update"]))
    result.setdefault("audit", []).append({
        "comment_id": comment_id, "comment_url": comment.get("html_url"),
        "author": comment.get("user", {}).get("login"), "received_at": comment.get("created_at"),
        "incident_id": value["incident_id"], "before": before, "change": deepcopy(value),
    })
    living.export(candidates, result)
    return result


def main():
    event = read_json(Path(os.environ["GITHUB_EVENT_PATH"]), {})
    path = ROOT / "data/living-evidence.json"
    overlay = read_json(path, {"schema_version": 1, "incidents": {}, "audit": []})
    try:
        incidents = read_json(ROOT / "data/incidents.json", [])
        history = read_json(ROOT / "data/living-history.json", [])
        if not isinstance(history, list) or any(not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip() for item in history):
            raise ValueError("Historical candidates must be an array with incident IDs")
        # Original IDs retain their publication status, including rejections.
        seen = {item.get("id") for item in incidents}
        combined = list(incidents)
        for item in history:
            if item["id"] not in seen:
                combined.append(item)
                seen.add(item["id"])
        result = apply_event(event, overlay, combined)
        # Derive persistence only after authorisation, validation and replay checks.
        candidate = prepare_candidate(parse(event.get("comment", {}).get("body")), combined) if result != overlay else None
    except ValueError as exc:
        # Validation messages are fixed strings; never echo untrusted comment content.
        raise SystemExit(str(exc)) from None
    if result != overlay:
        if candidate is not None:
            write_json(ROOT / "data/living-history.json", [*history, candidate])
        write_json(path, result)
    print("Living evidence validated; article data unchanged.")


if __name__ == "__main__":
    main()

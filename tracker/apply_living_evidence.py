"""Apply authorised /evidence JSON comments to the additive living tracker overlay."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

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
    if not isinstance(value, dict) or set(value) - {"incident_id", "casualties", "update", "image", "verification"}:
        raise ValueError("Unsupported evidence fields")
    return value


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
        if not isinstance(claim, dict) or set(claim) - {"status", "deaths", "sources", "nationalities"}:
            raise ValueError("Invalid casualty evidence")
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
    value = validate(parse(comment.get("body")), incidents)
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
    living.export(incidents, result)
    return result


def main():
    event = read_json(Path(os.environ["GITHUB_EVENT_PATH"]), {})
    path = ROOT / "data/living-evidence.json"
    overlay = read_json(path, {"schema_version": 1, "incidents": {}, "audit": []})
    try:
        result = apply_event(event, overlay, read_json(ROOT / "data/incidents.json", []))
    except ValueError as exc:
        # Validation messages are fixed strings; never echo untrusted comment content.
        raise SystemExit(str(exc)) from None
    if result != overlay:
        write_json(path, result)
    print("Living evidence validated; article data unchanged.")


if __name__ == "__main__":
    main()

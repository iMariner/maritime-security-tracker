"""Editor check: Hermes reads each morning's draft against the original sources before it reaches Telegram.

1. After the draft is built, `write_request` saves data/review/<date>.json: the incidents in the draft with
   their facts and source links, for Hermes to check.
2. Hermes comments on the pinned "Daily brief trigger" issue:

       /review 2026-10-05
       merge: INC-20261004-013 into INC-20261004-005 | same UKMTO 151-26 attack retold by a local outlet
       name: INC-20261004-002 = LIPSI | https://maritime-executive.com/article/...
       flag: INC-... = Liberia | <url>
       imo: INC-... = 1234567 | <url>
       date: INC-... = 2026-10-03 | <url>
       position: INC-... = 12.32, 43.25 | <where it comes from, e.g. 60 nm south of Al-Mokha per UKMTO>
       status: INC-... = rejected | <reason>
       note: <anything the publisher should know, one sentence>

   or just "ok" on the second line when nothing needs changing.
3. `apply` makes those changes to the incident data (only for incidents in that day's request) and records
   what was done in the brief record, which the Telegram message then shows.
"""
from __future__ import annotations

import argparse
import re

from . import incidents as store
from .common import BRIEFS_DIR, ROOT, env, iso, log, now_utc, read_json, write_json

REVIEW_DIR = ROOT / "data" / "review"
STATUSES = ("confirmed", "reported", "claimed", "rejected")
ID = r"(INC-\d{8}-\d{3})"


def _direct_sources(inc: dict, limit: int = 8) -> list[dict]:
    """Sources Hermes can open: the outlet's own page first, Google News redirects last."""
    srcs = [s for s in inc.get("sources", []) if s.get("source_type") != "satellite"]
    srcs.sort(key=lambda s: "news.google.com" in s.get("url", ""))
    return [{"outlet": s.get("source"), "title": s.get("title"), "url": s.get("url"),
             "published": s.get("published_at")} for s in srcs[:limit]]


def write_request(day: str, record: dict) -> None:
    by_id = {i["id"]: i for i in store.load()}
    items = []
    for x in record.get("incident_ids", []) + record.get("correction_ids", []):
        inc = by_id.get(x)
        if not inc:
            continue
        items.append({
            "id": inc["id"], "status": inc.get("status"), "region": inc.get("region"), "date_utc": inc.get("date_utc"),
            "vessel_name": inc.get("vessel_name"), "imo": inc.get("imo"), "flag": inc.get("flag"),
            "vessel_type": inc.get("vessel_type"), "location": inc.get("location_text"),
            "attack": inc.get("attack_type"), "damage": inc.get("damage"), "casualties": inc.get("casualties"),
            "attribution": inc.get("attribution_claimed"), "summary": inc.get("summary"),
            "checked_by_hermes": bool(inc.get("verdict")), "sources": _direct_sources(inc),
        })
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    write_json(REVIEW_DIR / f"{day}.json", {"date": day, "title": record.get("title"),
                                            "preview_url": record.get("preview_url"), "incidents": items})
    log.info("Editor check request written for %s (%d incidents)", day, len(items))


def parse(body: str) -> tuple[str, list[tuple], list[str]] | None:
    """Returns (date, changes, notes), or None if this is not a /review comment."""
    lines = [l.strip() for l in (body or "").strip().splitlines() if l.strip()]
    m = re.match(r"/review\s+(\d{4}-\d{2}-\d{2})\b", lines[0]) if lines else None
    if not m:
        return None
    changes, notes = [], []
    for line in lines[1:]:
        key, _, rest = line.partition(":")
        key, rest = key.strip().lower(), rest.strip()
        why = rest.partition("|")[2].strip()
        if key == "merge" and (mm := re.match(ID + r"\s+into\s+" + ID, rest, re.I)):
            changes.append(("merge", mm.group(1).upper(), mm.group(2).upper(), why))
        elif key in ("name", "flag", "imo", "date", "status", "position") and (mm := re.match(ID + r"\s*=\s*([^|]+)", rest, re.I)):
            changes.append((key, mm.group(1).upper(), mm.group(2).strip(), why))
        elif key == "lesson" and (mm := re.match(r"(writing|facts)\s*=\s*(.+)", rest, re.I)):
            changes.append(("lesson", mm.group(1).lower(), mm.group(2).strip(), ""))
        elif key == "note" and rest:
            notes.append(rest if len(rest) <= 600 else rest[:600].rsplit(" ", 1)[0] + "...")
        elif line.lower() != "ok":
            log.warning("Editor check: ignored line %r", line[:120])
    return m.group(1), changes, notes


def _source(url: str, cited: bool) -> dict | None:
    """The page Hermes gives as evidence. A page that supplied a fact (a name, flag, IMO, date) is listed and
    credited like any outlet; a page behind a status decision is kept as verification evidence only."""
    if not re.match(r"https?://\S+$", url or ""):
        return None
    outlet = re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*$", r"\1", url))
    kind = "media" if cited else "verification"
    return {"url": url, "source": outlet if cited else "Editor check", "source_type": kind, "side": "neutral",
            "kind": kind, "published_at": iso(now_utc()), "title": None}


def apply(body: str) -> str | None:
    """Apply a /review comment. Returns the review date, or None when there was nothing to apply."""
    from .consolidate import _merge_into

    parsed = parse(body)
    if not parsed:
        return None
    day, changes, notes = parsed
    request = read_json(REVIEW_DIR / f"{day}.json", {})
    allowed = {i["id"] for i in request.get("incidents", [])}
    incidents = store.load()
    by_id = {i["id"]: i for i in incidents}
    stamp = iso(now_utc())
    done, refused = [], []
    for kind, target, value, why in changes:
        if kind == "lesson":
            from . import lessons
            (done if lessons.add(target, value) else refused).append(f"lesson ({target}): {value[:120]}")
            continue
        inc = by_id.get(target)
        if target not in allowed or not inc:
            refused.append(f"{kind} {target}: not in today's draft")
            continue
        if kind == "merge":
            keep = by_id.get(value)
            if not keep or keep is inc:
                refused.append(f"merge {target}: unknown target {value}")
                continue
            _merge_into(keep, inc, sources_only=True)
            inc["status"], inc["last_updated"] = "merged", stamp
            keep["status"], keep["last_updated"] = store.compute_status(keep), stamp
            done.append(f"merged {target} into {value}" + (f" ({why})" if why else ""))
            continue
        if kind == "position":
            m = re.fullmatch(r"(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)", value)
            lat, lon = (float(m.group(1)), float(m.group(2))) if m else (None, None)
            # inside the areas we cover (Black Sea to the Gulf of Aden and the Gulf), never on another continent
            if lat is None or not (8 <= lat <= 48 and 26 <= lon <= 62) or not why:
                refused.append(f"position {target}: '{value}' is outside the covered areas or has no reason")
                continue
            inc["lat"], inc["lon"], inc["position_approx"] = lat, lon, True
            inc["position_note"] = why[:200]
            inc["last_updated"] = stamp
            done.append(f"position of {target} set to {lat}, {lon} ({why[:80]})")
            continue
        src = _source(why, cited=kind != "status")
        if kind in ("name", "flag", "imo", "date"):
            if kind == "imo" and not re.fullmatch(r"\d{7}", value):
                refused.append(f"imo {target}: '{value}' is not a 7-digit IMO number")
                continue
            if kind == "date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                refused.append(f"date {target}: '{value}' is not a date")
                continue
            if not src:
                refused.append(f"{kind} {target}: no source link given")
                continue
            field = {"name": "vessel_name", "flag": "flag", "imo": "imo", "date": "date_utc"}[kind]
            inc[field] = value.upper() if kind == "name" else value
            done.append(f"{kind} of {target} set to {inc[field]}")
        elif kind == "status":
            status = value.lower()
            if status not in STATUSES:
                refused.append(f"status {target}: '{value}' is not one of {', '.join(STATUSES)}")
                continue
            inc["verdict"] = {"status": status, "by": "editor-check", "at": stamp, "note": why or None}
            if inc.get("status") != status:
                inc["status_changed_at"] = stamp
            inc["status"] = status
            done.append(f"{target} marked {status}" + (f" ({why})" if why else ""))
        if src:
            inc["sources"].append(src)
        inc["last_updated"] = stamp
    store.save(incidents)
    record_path = BRIEFS_DIR / f"{day}.json"
    record = read_json(record_path, {})
    # A later /review the same day (a resend, a second check) adds to the first one instead of wiping its notes
    prev = record.get("review") or {}
    keep = lambda k, new: [x for x in prev.get(k) or [] if x not in new] + new if prev.get("status") == "done" else new
    record["review"] = {"status": "done", "at": stamp, "changes": keep("changes", done),
                        "refused": keep("refused", refused), "notes": keep("notes", notes)}
    write_json(record_path, record)
    log.info("Editor check for %s: %d change(s), %d refused, %d note(s)", day, len(done), len(refused), len(notes))
    for line in done + refused + notes:
        log.info("  %s", line)
    return day


def summary_line(record: dict) -> str:
    """One line for the Telegram message about whether the editor check ran and what it did."""
    review = record.get("review") or {}
    if review.get("status") != "done":
        return "⚠️ Editor check did not run: read the draft carefully before publishing."
    parts = []
    changes = review.get("changes") or []
    parts.append(f"Editor check: {len(changes)} fix(es) made ({'; '.join(changes)[:400]})" if changes
                 else "Editor check: no problems found")
    if review.get("refused"):
        parts.append(f"⚠️ {len(review['refused'])} suggested fix(es) could not be applied")
    if review.get("notes"):
        parts.append("⚠️ Editor notes (given to the writer, check the draft follows them): " + " ".join(review["notes"]))
    return ". ".join(parts) + "."


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="apply the /review comment in COMMENT_BODY")
    args = ap.parse_args()
    if args.apply:
        body = env("COMMENT_BODY", "")
        if body.strip().startswith("/lessons"):
            from . import lessons
            lessons.replace_from_comment(body)
            return
        day = apply(body)
        if day:
            print(f"day={day}")


if __name__ == "__main__":
    main()

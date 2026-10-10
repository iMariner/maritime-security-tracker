"""Editor check: Hermes reads each morning's draft against the original sources before it reaches Telegram.

1. After the draft is built, `write_request` saves data/review/<date>.json: the incidents in the draft with
   their facts and source links, for Hermes to check.
2. Hermes comments on the pinned "Daily brief trigger" issue:

       /review 2026-10-05
       merge: INC-20261004-013 into INC-20261004-005 | same UKMTO 151-26 attack retold by a local outlet
       unmerge: INC-20261007-003 | a different attack wrongly merged into another record; it becomes its own incident
       name: INC-20261004-002 = LIPSI | https://maritime-executive.com/article/...
       flag: INC-... = Liberia | <url>
       imo: INC-... = 1234567 | <url>
       date: INC-... = 2026-10-03 | <url>
       position: INC-... = 12.32, 43.25 | <where it comes from, e.g. 60 nm south of Al-Mokha per UKMTO>
       casualties: INC-... = <what the sources say, or none> | <link or reason>
       damage: INC-... = <what the sources say, or none> | <link or reason>
       region: INC-... = Persian Gulf | <why>
       flag: INC-... = none | <why a wrong flag is cleared>
       lead: INC-... | <why this attack leads today's brief>
       status: INC-... = rejected | <reason>
       note: <anything the publisher should know, one sentence>

   or just "ok" on the second line when nothing needs changing.
3. `apply` makes those changes to the incident data (only for incidents in that day's request) and records
   what was done in the brief record, which the Telegram message then shows.
"""
from __future__ import annotations

import argparse
import re
from datetime import timedelta

from . import incidents as store
from .common import BRIEFS_DIR, ROOT, env, iso, log, now_utc, parse_dt, read_json, write_json

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
    send = False
    for line in lines[1:]:
        key, _, rest = line.partition(":")
        key, rest = key.strip().lower(), rest.strip()
        why = rest.partition("|")[2].strip()
        if key == "merge" and (mm := re.match(ID + r"\s+into\s+" + ID, rest, re.I)):
            changes.append(("merge", mm.group(1).upper(), mm.group(2).upper(), why))
        elif key in ("unmerge", "restore") and (mm := re.match(ID, rest, re.I)):
            changes.append(("unmerge", mm.group(1).upper(), "", why))
        elif key == "lead" and (mm := re.match(ID, rest, re.I)):
            changes.append(("lead", mm.group(1).upper(), "", why))
        elif key in ("name", "flag", "imo", "date", "status", "position", "casualties", "damage", "region") \
                and (mm := re.match(ID + r"\s*=\s*([^|]+)", rest, re.I)):
            changes.append((key, mm.group(1).upper(), mm.group(2).strip(), why))
        elif key == "lesson" and (mm := re.match(r"(writing|facts)\s*=\s*(.+)", rest, re.I)):
            changes.append(("lesson", mm.group(1).lower(), mm.group(2).strip(), ""))
        elif key == "send" and rest.lower().startswith("yes"):
            send = True
        elif key == "note" and rest:
            notes.append(rest if len(rest) <= 600 else rest[:600].rsplit(" ", 1)[0] + "...")
            if re.match(r"automatic resend\b", rest, re.I):  # the 06:00 watchdog: send now
                send = True
        elif line.lower() != "ok":
            log.warning("Editor check: ignored line %r", line[:120])
    if send:
        changes.append(("send", "", "", ""))
    return m.group(1), changes, notes


def parse_send(body: str) -> tuple[str, list[str]] | None:
    """'/send YYYY-MM-DD' from the final read (or the watchdog): send the draft as it is, with optional
    'warning: ...' lines that go into the approval message. Returns (date, warnings)."""
    lines = [l.strip() for l in (body or "").strip().splitlines() if l.strip()]
    m = re.match(r"/send\s+(\d{4}-\d{2}-\d{2})\b", lines[0]) if lines else None
    if not m:
        return None
    warnings = [l.partition(":")[2].strip()[:400] for l in lines[1:] if l.lower().startswith("warning:")]
    return m.group(1), [w for w in warnings if w]


def apply_send(body: str) -> str | None:
    parsed = parse_send(body)
    if not parsed:
        return None
    day, warnings = parsed
    record_path = BRIEFS_DIR / f"{day}.json"
    record = read_json(record_path, {})
    if not record.get("post_id"):
        log.warning("/send %s: no brief record for that day", day)
        return None
    record["final_read"] = {"status": "warnings" if warnings else "ok", "at": iso(now_utc()), "warnings": warnings}
    write_json(record_path, record)
    log.info("Final read for %s: %s", day, "; ".join(warnings) or "no problems")
    return day


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
    done, refused, restored = [], [], []
    lead = None
    send = any(c[0] == "send" for c in changes)
    for kind, target, value, why in changes:
        if kind == "send":
            continue
        if kind == "lesson":
            from . import lessons
            (done if lessons.add(target, value) else refused).append(f"lesson ({target}): {value[:120]}")
            continue
        inc = by_id.get(target)
        if kind == "unmerge":
            # the record is merged, so it is not in today's request; allow recent ones only
            recent = inc and (parse_dt(inc.get("date_utc")) or parse_dt(inc.get("first_seen")))
            if not inc or not inc.get("merged_into") or not recent or \
                    abs(recent.date() - parse_dt(day).date()) > timedelta(days=3):
                refused.append(f"unmerge {target}: not a recently merged record")
                continue
            keep = by_id.get(inc["merged_into"])
            own = {s.get("url") for s in inc.get("sources", [])}
            if keep:
                keep["sources"] = [s for s in keep["sources"] if s.get("url") not in own] or keep["sources"]
                keep.setdefault("keep_apart", [])
                keep["keep_apart"] = sorted(set(keep["keep_apart"]) | {target})
                keep["status"], keep["last_updated"] = store.compute_status(keep), stamp
            inc.pop("merged_into", None)
            inc["keep_apart"] = sorted(set(inc.get("keep_apart") or []) | ({keep["id"]} if keep else set()))
            inc["status"] = store.compute_status(inc)
            inc["status_changed_at"] = inc["last_updated"] = stamp
            restored.append(target)
            done.append(f"{target} separated from {keep['id'] if keep else 'its merge'}" + (f" ({why})" if why else ""))
            continue
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
        if kind == "lead":
            lead = target
            done.append(f"lead story set to {target}" + (f" ({why[:80]})" if why else ""))
            continue
        if kind in ("casualties", "damage"):
            text = value.strip()[:300]
            if not why:
                refused.append(f"{kind} {target}: no source or reason given")
                continue
            inc[kind] = None if text.lower() in ("none", "none reported", "unknown", "clear") else text
            inc["last_updated"] = stamp
            src = _source(why, cited=True)
            if src:
                inc["sources"].append(src)
            done.append(f"{kind} of {target} set to {inc[kind] or 'none'}")
            continue
        if kind == "region":
            from .consolidate import ALL_REGIONS
            region = next((r for r in ALL_REGIONS if r.lower() == value.strip().lower()), None)
            if not region:
                refused.append(f"region {target}: '{value}' is not one of {', '.join(ALL_REGIONS)}")
                continue
            inc["region"], inc["last_updated"] = region, stamp
            done.append(f"region of {target} set to {region}")
            continue
        if kind == "flag" and value.strip().lower() in ("none", "unknown", "clear"):
            if not why:
                refused.append(f"flag {target}: clearing needs a reason")
                continue
            inc.pop("flag", None)
            inc["last_updated"] = stamp
            done.append(f"flag of {target} cleared ({why[:80]})")
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
            new_value = value.upper() if kind == "name" else value
            if inc.get(field) != new_value and kind in ("name", "flag"):
                inc["news_changed_at"] = stamp  # a ship newly identified is news for the next brief
            inc[field] = new_value
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
                        "refused": keep("refused", refused), "notes": keep("notes", notes),
                        "restored": keep("restored", restored), "send_after": send,
                        "lead": lead or prev.get("lead")}
    if send and not record.get("final_read"):
        # '/review ... send: yes' is the final read (or the owner's feedback) fixing the draft before it goes out
        record["final_read"] = {"status": "fixed", "at": stamp, "warnings": []}
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
    parts.append(f"Editor check: {len(changes)} fix(es) made ({'; '.join(changes)[:250]})" if changes
                 else "Editor check: no problems found")
    if review.get("refused"):
        parts.append(f"⚠️ {len(review['refused'])} suggested fix(es) could not be applied")
    final = record.get("final_read") or {}
    if final.get("status") == "ok":
        parts.append("Final read: no problems found")
    elif final.get("status") == "fixed":
        parts.append("Final read: fixes made before sending")
    elif final.get("status") == "warnings":
        parts.append("⚠️ Final read: " + " ".join(final.get("warnings") or []))
    elif review.get("status") == "done":
        parts.append("⚠️ The final read of this draft did not run")
    if review.get("notes"):
        if final.get("status"):  # the final read already checked the draft follows them: keep the message short
            parts.append(f"Editor notes: {len(review['notes'])} given to the writer")
        else:
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
        if body.strip().startswith("/send"):
            day = apply_send(body)
            if day:
                print(f"day={day}")
                print("mode=send")  # send the draft as it is
            return
        day = apply(body)
        if day:
            review = read_json(BRIEFS_DIR / f"{day}.json", {}).get("review") or {}
            print(f"day={day}")
            # rebuild; hold it for the final read unless this review says to send straight away
            print("mode=rebuild-send" if review.get("send_after") else "mode=rebuild-hold")


if __name__ == "__main__":
    main()

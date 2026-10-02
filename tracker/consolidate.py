"""Review pass: look at a region's recent incidents together and merge the ones that are the same
real-world attack, and drop the ones that are out of scope.

Per-report matching sees one report at a time, so different outlets' versions of the same attack
("three ships hit" / "four tankers attacked" / "tanker on fire") can survive as separate incidents.
This pass sees them all at once: one AI call per region group per run.
"""
from __future__ import annotations

import json
import re
from datetime import timedelta

from . import github_issues, llm
from .common import iso, load_yaml, log, no_em_dash, now_utc, parse_dt
from .incidents import MERGE_FIELDS, compute_status, different_flags, has_official, same_vessel

GROUPS = {
    "Hormuz and Gulf": {"Strait of Hormuz", "Persian Gulf", "Gulf of Oman", "Red Sea", "Gulf of Aden"},
    "Black Sea": {"Black Sea", "Sea of Azov"},
}
WINDOW = timedelta(days=10)
ALL_REGIONS = ["Black Sea", "Sea of Azov", "Strait of Hormuz", "Persian Gulf", "Gulf of Oman", "Red Sea", "Gulf of Aden"]
CLOSED = ("rejected", "merged")


def _event_time(inc: dict):
    return parse_dt(inc.get("date_utc")) or parse_dt(inc.get("first_seen"))


def _brief(inc: dict) -> dict:
    return {
        "id": inc["id"], "region": inc.get("region"), "date": (inc.get("date_utc") or "")[:10],
        "date_is_publish_date": bool(inc.get("date_approx")), "vessel": inc.get("vessel_name"),
        "type": inc.get("vessel_type"), "category": inc.get("vessel_category"), "attack": inc.get("attack_type"),
        "where": inc.get("location_text"), "summary": (inc.get("summary") or "")[:300],
        "headlines": [s.get("title") or s["source"] for s in inc["sources"][:6] if s.get("source_type") != "satellite"],
        "verdict": (inc.get("verdict") or {}).get("status"),
    }


def _system(regions_on: list[str]) -> str:
    return (
        "You are the editor checking a maritime security incident log for duplicates before publication.\n"
        "You get the recent incidents for one area. Several entries often describe the SAME real-world attack, "
        "because different outlets report it with different wording, counts or dates (e.g. 'three ships hit', "
        "'four tankers attacked in 24 hours', 'tanker catches fire', a named vessel). A roundup that reports "
        "several attacks together is the same event as the individual entries it covers.\n"
        "Tasks:\n"
        "1. Group entries that are the same real-world attack (or the same cluster of attacks reported together). "
        "Merge only when the details clearly fit: same area, dates within about two days, compatible vessel and "
        "attack details, overlapping headlines. When unsure, do not merge.\n"
        "2. Mark an entry out of scope ONLY for one of these reasons: (a) no vessel was attacked at all (a strike "
        "on a port, terminal or land with no ship hit); (b) the target was a warship or military vessel; (c) it "
        "describes no specific incident at all (general commentary, statistics, policy news). These are NOT "
        "reasons to drop an entry: the vessel is not named, there is only one source, it is an unconfirmed claim "
        "by one side (claims are published as claims), or details are thin. "
        f"Every one of these areas is IN scope: {', '.join(regions_on)}.\n"
        'Return JSON: {"groups": [{"keep": "<id>", "keep_attack_date": "YYYY-MM-DD", '
        '"merge": [{"id": "<id>", "attack_date": "YYYY-MM-DD"}], "vessel_name": "<name or null>", '
        '"summary": "<2 plain sentences describing the event, attributing claims, no em dashes>"}], '
        '"out_of_scope": [{"id": "<id>", "reason": "<short reason>"}]}. '
        "attack_date is the day the attack itself happened according to that entry's text and headlines, NOT the "
        "day the article was published (a 1 October article about 'late reports of attacks on 28 and 29 September' "
        "has attack_date 2026-09-29). Entries whose attacks are more than two days apart are different events.\n"
        "3. Correct an entry's region when it is clearly wrong (e.g. Yanbu, Jeddah or Houthi attacks off Yemen are "
        f"Red Sea; Aden is Gulf of Aden). Allowed regions: {', '.join(ALL_REGIONS)}.\n"
        "The out_of_scope reason must name which of (a), (b) or (c) applies. "
        "Also return \"region_fixes\": [{\"id\": \"<id>\", \"region\": \"<correct region>\"}] (empty if none). "
        "Only list groups that merge at least one entry. 'keep' is the entry with the most specific details "
        "(a named vessel or an official confirmation). Never invent details."
    )


IDENTITY = ("vessel_name", "imo", "flag", "vessel_type", "vessel_category", "lat", "lon", "location_text")


def _merge_into(keep: dict, other: dict, sources_only: bool = False) -> None:
    """Fold `other` into `keep`. With sources_only, only its sources and evidence are added: nothing about
    the vessel (name, flag, type, position) is copied, used when filing roundups under an official record."""
    urls = {s["url"] for s in keep["sources"]}
    for s in other["sources"]:
        if s["url"] not in urls:
            keep["sources"].append(s)
            urls.add(s["url"])
    for f in MERGE_FIELDS + ("official_source_cited",):
        if sources_only and f in IDENTITY:
            continue
        if keep.get(f) in (None, "") and other.get(f) not in (None, ""):
            keep[f] = other[f]
    keep["independent_evidence"] = bool(keep.get("independent_evidence") or other.get("independent_evidence"))
    keep["confidence"] = max(keep.get("confidence") or 0, other.get("confidence") or 0)
    if not keep.get("verdict") and (other.get("verdict") or {}).get("status") in ("confirmed", "reported"):
        keep["verdict"] = other["verdict"]
    keep["published_in"] = sorted(set(keep.get("published_in") or []) | set(other.get("published_in") or []))
    other["merged_into"] = keep["id"]


def _close(inc: dict, why: str) -> None:
    if inc.get("verification_issue"):
        try:
            github_issues.close_issue(inc["verification_issue"], why)
        except Exception as exc:  # closing an issue is housekeeping; never fail the run for it
            log.warning("Could not close issue #%s: %s", inc["verification_issue"], exc)


def absorb_into_official(incidents: list[dict]) -> int:
    """Unnamed reports ('three tankers hit', 'a tanker struck') around official, named records (IMO list)
    become supporting sources of the official record on the nearest date in the same area. The official
    record keeps its own summary. Returns how many were absorbed."""
    stamp = iso(now_utc())
    absorbed = 0
    for group in GROUPS.values():
        official = [i for i in incidents if i.get("region") in group and has_official(i) and i.get("vessel_name")
                    and i.get("status") not in CLOSED and not i.get("merged_into") and _event_time(i)]
        if not official:
            continue
        for inc in incidents:
            # Only generic reports: a report naming a flag or IMO number describes a specific ship.
            if (inc.get("region") not in group or inc.get("vessel_name") or inc.get("flag") or inc.get("imo")
                    or has_official(inc)
                    or inc.get("status") in CLOSED or inc.get("merged_into") or not _event_time(inc)):
                continue
            near = [o for o in official if abs(_event_time(o) - _event_time(inc)) <= timedelta(days=1)
                    and not different_flags(o, inc)]
            if not near:
                continue
            target = min(near, key=lambda o: abs(_event_time(o) - _event_time(inc)))
            _merge_into(target, inc, sources_only=True)
            inc["status"], inc["last_updated"] = "merged", stamp
            target["status"], target["last_updated"] = compute_status(target), stamp
            _close(inc, f"Closed: covered by the official IMO record {target['id']} ({target['vessel_name']}).")
            absorbed += 1
            log.info("Absorbed unnamed %s into official %s (%s)", inc["id"], target["id"], target["vessel_name"])
    return absorbed


def consolidate(incidents: list[dict]) -> int:
    """Merge duplicates and drop out-of-scope incidents in place. Returns how many entries were closed."""
    closed = absorb_into_official(incidents)
    if not llm.available():
        return closed
    regions_on = [r["name"] for r in load_yaml("regions.yaml").get("regions", []) if r.get("enabled")]
    cutoff = now_utc() - WINDOW
    by_id = {i["id"]: i for i in incidents}
    stamp = iso(now_utc())
    for group, regions in GROUPS.items():
        live = [i for i in incidents if i.get("region") in regions and i.get("status") not in CLOSED
                and not i.get("merged_into") and (_event_time(i) or now_utc()) >= cutoff]
        if len(live) < 2 and not any(i.get("region") not in regions_on for i in live):
            continue
        try:
            answer = llm.chat_json(_system(regions_on), json.dumps({"area": group, "incidents": [_brief(i) for i in live]},
                                                                   ensure_ascii=False), max_tokens=4000)
        except RuntimeError as exc:
            log.warning("Review pass for %s skipped: %s", group, exc)
            continue
        live_ids = {i["id"] for i in live}
        for g in answer.get("groups") or []:
            keep = by_id.get(g.get("keep"))
            if not keep or keep["id"] not in live_ids or keep.get("merged_into"):
                continue
            merged = []
            keep_day = parse_dt(g.get("keep_attack_date"))
            for m in g.get("merge") or []:
                mid = m.get("id") if isinstance(m, dict) else m
                other = by_id.get(mid)
                if not other or other is keep or other["id"] not in live_ids or other.get("merged_into"):
                    continue
                # Hard rules the model cannot override.
                day = parse_dt(m.get("attack_date")) if isinstance(m, dict) else None
                if not (keep_day and day) or abs(keep_day - day) > timedelta(days=2):
                    log.info("Review: not merging %s into %s (attack dates %s / %s)", mid, keep["id"],
                             g.get("keep_attack_date"), m.get("attack_date") if isinstance(m, dict) else None)
                    continue
                if different_flags(keep, other):
                    log.info("Review: not merging %s into %s (different flags)", mid, keep["id"])
                    continue
                if has_official(other) and not has_official(keep):
                    log.info("Review: not merging official record %s into %s", mid, keep["id"])
                    continue  # absorb_into_official() handles unnamed reports around official records
                if keep.get("vessel_name") and other.get("vessel_name") and \
                        not same_vessel(keep["vessel_name"], other["vessel_name"]):
                    log.info("Review: not merging %s into %s (different vessels)", mid, keep["id"])
                    continue
                _merge_into(keep, other)
                other["status"], other["last_updated"] = "merged", stamp
                _close(other, f"Closed: same attack as {keep['id']}, merged there.")
                merged.append(other["id"])
            if not merged:
                continue
            proposed = {m.get("id") if isinstance(m, dict) else m for m in g.get("merge") or []}
            whole_group = proposed <= set(merged)  # the model's summary describes every proposed member
            if g.get("vessel_name") and (not keep.get("vessel_name") or (
                    len(g["vessel_name"]) > len(keep["vessel_name"]) and same_vessel(g["vessel_name"], keep["vessel_name"]))):
                keep["vessel_name"] = g["vessel_name"]  # prefer the fuller registered name
            if keep_day:
                keep["date_utc"], keep["date_approx"] = g["keep_attack_date"], False
            if g.get("summary") and whole_group and not has_official(keep):
                keep["summary"] = no_em_dash(g["summary"])
            keep["status"] = compute_status(keep)
            keep["last_updated"] = stamp
            closed += len(merged)
            log.info("Review: merged %s into %s", ", ".join(merged), keep["id"])
        for fix in answer.get("region_fixes") or []:
            inc = by_id.get(fix.get("id"))
            if inc and inc["id"] in live_ids and fix.get("region") in ALL_REGIONS and fix["region"] != inc.get("region"):
                log.info("Review: %s region %s -> %s", inc["id"], inc.get("region"), fix["region"])
                inc["region"], inc["last_updated"] = fix["region"], stamp
        for o in answer.get("out_of_scope") or []:
            inc = by_id.get(o.get("id"))
            if not inc or inc["id"] not in live_ids or inc.get("merged_into") or inc.get("status") in CLOSED:
                continue
            note = no_em_dash(o.get("reason") or "out of scope")
            # (c) "no specific incident" is only believable for an entry with no vessel type and no location.
            if not re.match(r"\s*\(?[ab]\)", note) and (inc.get("vessel_type") or inc.get("location_text")):
                log.info("Review: keeping %s (model said out of scope, but it names a vessel type or place: %s)", inc["id"], note)
                continue
            inc["verdict"] = {"status": "rejected", "by": "review pass", "at": stamp, "note": f"Out of scope: {note}"}
            inc["status"], inc["last_updated"] = "rejected", stamp
            _close(inc, f"Closed: out of scope ({note}).")
            closed += 1
            log.info("Review: %s out of scope (%s)", inc["id"], note)
    return closed

"""Incident store: match new reports to known incidents, merge sources, and set status.

Status ladder (weakest to strongest):
  signal     satellite/AIS lead only, never published
  claimed    only one side of the conflict says it happened
  reported   independent media, or both sides, or two unrelated outlets
  confirmed  a neutral authority or the owner confirms it, or a verifier said so
  rejected   checked and found false (kept so it is not re-added)
"""
from __future__ import annotations

import json
import math
import re
from datetime import timedelta
from difflib import SequenceMatcher

from . import llm
from .common import INCIDENTS_FILE, iso, log, no_em_dash, now_utc, parse_dt, read_json, write_json

NAME_WINDOW = timedelta(days=4)
UNNAMED_WINDOW = timedelta(hours=36)
FIRMS_WINDOW = timedelta(hours=12)
MERGE_FIELDS = ("vessel_name", "imo", "flag", "vessel_type", "vessel_category", "lat", "lon", "location_text",
                "attack_type", "damage", "casualties", "attribution_claimed")
_PREFIX = re.compile(r"^(m/?v|m/?t|mt|mv|ms|lng|lpg|ss|tanker|vessel)\s+", re.I)


def load() -> list[dict]:
    return read_json(INCIDENTS_FILE, [])


def save(incidents: list[dict]) -> None:
    incidents.sort(key=lambda x: x.get("date_utc") or x.get("first_seen") or "", reverse=True)
    write_json(INCIDENTS_FILE, incidents)


def norm_name(name: str | None) -> str:
    if not name:
        return ""
    name = _PREFIX.sub("", name.strip())
    return re.sub(r"[^a-z0-9]", "", name.lower())


def km(a_lat, a_lon, b_lat, b_lon) -> float:
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _when(x: dict):
    return (parse_dt(x.get("date_utc")) or parse_dt((x.get("source") or {}).get("published_at"))
            or parse_dt(x.get("_published")) or parse_dt(x.get("first_seen")))


def _close_in_time(a, b, window) -> bool:
    ta, tb = _when(a), _when(b)
    return bool(ta and tb and abs(ta - tb) <= window)


def find_match(report: dict, incidents: list[dict], model_checked: bool = False) -> dict | None:
    """Strong identifiers first (IMO, vessel name), then the extraction model's own `same_as` answer.
    Position and an extra AI call are used only when the model has not already compared the report
    against the known incidents (`model_checked`)."""
    imo = (report.get("imo") or "").strip()
    name = norm_name(report.get("vessel_name"))
    live = incidents  # rejected ones included, so a false report is not re-added as new

    if imo:
        for inc in live:
            if inc.get("imo") == imo:
                return inc
    if name:
        for inc in live:
            other = norm_name(inc.get("vessel_name"))
            if other and (other == name or SequenceMatcher(None, other, name).ratio() >= 0.85) and _close_in_time(report, inc, NAME_WINDOW):
                return inc
        # A named report can still be the first named account of an earlier unnamed incident.
    hinted = next((i for i in live if i["id"] == report.get("same_as")), None)
    if hinted and not (name and hinted.get("vessel_name") and norm_name(hinted["vessel_name"]) != name) \
            and not (imo and hinted.get("imo") and hinted["imo"] != imo):
        return hinted
    if model_checked:
        return None
    candidates = [
        inc for inc in live
        if inc.get("region") == report.get("region") and _close_in_time(report, inc, UNNAMED_WINDOW)
        and not (name and inc.get("vessel_name") and norm_name(inc.get("vessel_name")) != name)
    ]
    if not candidates:
        return None
    if all(x is not None for x in (report.get("lat"), report.get("lon"))):
        near = [c for c in candidates if c.get("lat") is not None and not c.get("position_approx") and km(report["lat"], report["lon"], c["lat"], c["lon"]) <= 60]
        if len(near) == 1:
            return near[0]
    return _ai_choose(report, candidates)


def _ai_choose(report: dict, candidates: list[dict]) -> dict | None:
    if not llm.available():
        return None
    brief = lambda x: {k: x.get(k) for k in ("vessel_name", "vessel_type", "date_utc", "location_text", "attack_type", "damage", "summary")}
    system = ("You decide whether a new report describes the same real-world attack as one of the known incidents. "
              'Answer JSON: {"match": "<incident id>" or null, "reason": "..."}. Only match when the details clearly fit.')
    user = json.dumps({"new_report": brief(report), "known_incidents": [{"id": c["id"], **brief(c)} for c in candidates[:8]]},
                      ensure_ascii=False)
    try:
        answer = llm.chat_json(system, user, max_tokens=300)
    except RuntimeError as exc:
        log.warning("Matching AI call failed, treating as new: %s", exc)
        return None
    return next((c for c in candidates if c["id"] == answer.get("match")), None)


# Only these count as neutral confirmation. Party militaries and governments never do, whatever the model says.
NEUTRAL_AUTHORITIES = re.compile(
    r"ukmto|jmic|marad|msci|nato|shipping centre|coast ?guard|flag state|registry|\bowner|manager|operator|"
    r"imb|piracy reporting|eunavfor|aspides|atalanta|combined maritime forces|\bcmf\b|ambrey|lloyd|"
    r"compan|shipping|tankers?\b|lines\b|maritime\b|\bp&i\b", re.I)
PARTY_AUTHORITIES = re.compile(r"russia|ukrain|iran|irgc|houthi|ministry of defen|\bmod\b|armed forces|navy|military|kremlin|zelensk|putin", re.I)


def neutral_confirmation(cited: str | None) -> bool:
    return bool(cited and NEUTRAL_AUTHORITIES.search(cited) and not PARTY_AUTHORITIES.search(cited))


def compute_status(inc: dict) -> str:
    if inc.get("verdict"):
        return inc["verdict"]["status"]
    sources = [s for s in inc.get("sources", []) if s.get("source_type") != "satellite"]
    if not sources:
        return "signal"
    if neutral_confirmation(inc.get("official_source_cited")):
        return "confirmed"
    sides = {s.get("side") for s in sources}
    if {"ua", "ru"} <= sides:
        return "reported"  # both sides of the conflict describe it
    if inc.get("independent_evidence") is not None:
        # Outlets repeating one party's statement are not independent evidence, however many there are.
        return "reported" if inc["independent_evidence"] else "claimed"
    # Incidents stored before the model judged evidence: the older outlet-count rule.
    outlets = {s.get("source") for s in sources}
    if "neutral" in sides or (len(outlets) >= 2 and any(s.get("kind") != "official" for s in sources)):
        return "reported"
    return "claimed"


def needs_verification(inc: dict) -> bool:
    if inc.get("verdict") or inc.get("verification_issue"):
        return False
    status = inc.get("status")
    return status == "signal" or inc.get("conflicting") or (status == "claimed" and (inc.get("confidence") or 0) < 0.6)


def _new_id(incidents: list[dict], when) -> str:
    day = (when or now_utc()).strftime("%Y%m%d")
    n = sum(1 for i in incidents if i["id"].startswith(f"INC-{day}-")) + 1
    return f"INC-{day}-{n:03d}"


def merge(report: dict, incidents: list[dict], model_checked: bool = False) -> tuple[dict, bool]:
    """Add one extracted report to the store. Returns (incident, is_new)."""
    source = report.pop("source")
    report["_published"] = source.get("published_at")
    stamp = iso(now_utc())
    match = find_match(report, incidents, model_checked)
    if match is None:
        inc = {k: report.get(k) for k in ("region", "date_utc", "summary", "official_source_cited", "conflicting", "confidence") + MERGE_FIELDS}
        inc["independent_evidence"] = bool(report.get("independent_evidence"))
        if not parse_dt(inc.get("date_utc")) and parse_dt(source.get("published_at")):
            # No date in the text: use the article's publish time and say it is approximate.
            inc["date_utc"], inc["date_approx"] = source["published_at"], True
        inc.update(id=_new_id(incidents, _when(report)), sources=[source], first_seen=stamp, last_updated=stamp,
                   verification_issue=None, verdict=None, published_in=[])
        inc["summary"] = no_em_dash(inc.get("summary") or "")
        inc["status"] = compute_status(inc)
        incidents.append(inc)
        return inc, True

    inc = match
    changed = False
    if source["url"] not in {s["url"] for s in inc["sources"]}:
        inc["sources"].append(source)
        changed = True
    if inc.get("position_approx") and report.get("lat") is not None and report.get("lon") is not None:
        inc["lat"], inc["lon"], inc["position_approx"] = report["lat"], report["lon"], False  # real position beats the guess
        changed = True
    for field in MERGE_FIELDS:
        if report.get(field) not in (None, "") and inc.get(field) in (None, ""):
            inc[field] = report[field]
            changed = True
    if report.get("official_source_cited") and not inc.get("official_source_cited"):
        inc["official_source_cited"] = report["official_source_cited"]
        changed = True
    # A stronger source rewrites the summary (neutral beats party sources).
    if report.get("summary") and source.get("side") == "neutral" and not any(
        s.get("side") == "neutral" for s in inc["sources"][:-1]
    ):
        inc["summary"] = no_em_dash(report["summary"])
        changed = True
    inc["confidence"] = max(inc.get("confidence") or 0, report.get("confidence") or 0)
    inc["conflicting"] = bool(inc.get("conflicting") or report.get("conflicting"))
    if report.get("independent_evidence"):
        inc["independent_evidence"] = True
    status = compute_status(inc)
    if status != inc.get("status"):
        inc["status"] = status
        changed = True
    if changed:
        inc["last_updated"] = stamp
    return inc, False


def add_firms_signal(det: dict, incidents: list[dict]) -> dict | None:
    """Attach a fire detection to a nearby incident, or open a signal incident if it is offshore."""
    sat_source = {"url": f"https://firms.modaps.eosdis.nasa.gov/map/#d:24hrs;@{det['lon']},{det['lat']},11z",
                  "source": f"NASA FIRMS ({det['sensor']})", "source_type": "satellite", "side": "neutral",
                  "kind": "data", "published_at": det["time"], "title": None}
    probe = {"date_utc": det["time"]}
    for inc in incidents:
        if inc.get("lat") is not None and not inc.get("position_approx") and _close_in_time(probe, inc, FIRMS_WINDOW) and km(det["lat"], det["lon"], inc["lat"], inc["lon"]) <= 15:
            if sat_source["url"] not in {s["url"] for s in inc["sources"]}:
                inc["sources"].append(sat_source)
                inc["last_updated"] = iso(now_utc())
            return inc
    kind, place = det["where"]
    if kind != "offshore":
        return None
    stamp = iso(now_utc())
    inc = {"id": _new_id(incidents, parse_dt(det["time"])), "region": place, "date_utc": det["time"],
           "vessel_name": None, "imo": None, "flag": None, "vessel_type": None, "vessel_category": None,
           "location_text": f"Offshore, {det['lat']:.3f}N {det['lon']:.3f}E", "lat": det["lat"], "lon": det["lon"],
           "attack_type": None, "damage": None, "casualties": None, "attribution_claimed": None,
           "official_source_cited": None, "conflicting": False, "confidence": 0.2,
           "summary": f"Satellite fire detection at sea ({det['sensor']}, FRP {det.get('frp')} MW). Cause unknown; needs checking.",
           "sources": [sat_source], "first_seen": stamp, "last_updated": stamp, "verification_issue": None,
           "verdict": None, "published_in": []}
    inc["status"] = compute_status(inc)
    incidents.append(inc)
    return inc

"""IMO 'Middle East: Highlighted (Confirmed) incidents' table: the official list of ships hit, with names
and IMO numbers. Each row becomes a confirmed incident directly; no AI call is needed to read it.

https://www.imo.org/en/mediacentre/hottopics/pages/middle-east-highlighted-incidents.aspx
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from ..common import USER_AGENT, iso, log, now_utc

URL = "https://www.imo.org/en/mediacentre/hottopics/pages/middle-east-highlighted-incidents.aspx"
SOURCE = "IMO (confirmed incidents list)"
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                       "september", "october", "november", "december"], 1)}
REGION_RULES = [
    (r"red sea|yanbu|jeddah|hodeidah|hudaydah|bab[- ]el[- ]mandeb|eritrea|port sudan|eilat|aqaba", "Red Sea"),
    (r"gulf of aden|\baden\b|djibouti|somali", "Gulf of Aden"),
    (r"fujairah|khor fakkan|gulf of oman|sohar|muscat|jask|chabahar|duqm", "Gulf of Oman"),
    (r"ras tanura|kuwait|qatar|bahrain|persian gulf|arabian gulf|dubai|jebel ali|abu dhabi|bandar|ras laffan|basra", "Persian Gulf"),
    (r"hormuz|khasab|musandam|larak|qeshm|hormoz|kish", "Strait of Hormuz"),
]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def region_for(location: str) -> str:
    for pattern, region in REGION_RULES:
        if re.search(pattern, location, re.I):
            return region
    return "Strait of Hormuz"


def parse(html: str, today: datetime | None = None) -> list[dict]:
    """Rows of the table as dicts: date (UTC midnight), name, imo, location, description."""
    today = today or now_utc()
    soup = BeautifulSoup(html, "html.parser")
    as_at = re.search(r"as at\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", _clean(soup.get_text(" ")))
    ref = datetime(int(as_at.group(3)), MONTHS[as_at.group(2).lower()], int(as_at.group(1)), tzinfo=timezone.utc) \
        if as_at and as_at.group(2).lower() in MONTHS else today
    rows = []
    for tr in soup.select("table tr"):
        cells = [_clean(td.get_text(" ")) for td in tr.find_all("td")]
        if len(cells) < 4:
            continue
        m = re.match(r"(\d{1,2})\s+([A-Za-z]+)", cells[0])
        ship = re.match(r"(.+?)\s*\(IMO\s*(\d{7})\)", cells[1])
        if not m or not ship or m.group(2).lower() not in MONTHS:
            continue
        month, day = MONTHS[m.group(2).lower()], int(m.group(1))
        year = ref.year if month <= ref.month else ref.year - 1  # the table has no years; it runs back from 'as at'
        rows.append({"date": datetime(year, month, day, tzinfo=timezone.utc), "name": ship.group(1).strip().upper(),
                     "imo": ship.group(2), "location": cells[2], "description": cells[3]})
    return rows


def to_report(row: dict, as_published: str) -> dict:
    desc = row["description"]
    casualties = " ".join(s for s in re.split(r"(?<=\.)\s+", desc) if re.search(r"fatalit|killed|injur|missing", s, re.I)) or None
    day = row["date"].strftime("%-d %B %Y")
    return {
        "region": region_for(row["location"]), "vessel_name": row["name"], "imo": row["imo"], "flag": None,
        "vessel_type": None, "vessel_category": "merchant", "date_utc": iso(row["date"]),
        "location_text": row["location"], "lat": None, "lon": None, "attack_type": "other",
        "damage": desc, "casualties": casualties, "attribution_claimed": None,
        "official_source_cited": "IMO confirmed incidents list", "independent_evidence": True,
        "conflicting": False, "confidence": 1.0, "is_recap": False,
        "summary": f"The IMO lists {row['name']} (IMO {row['imo']}) as hit at {row['location']} on {day}. {desc}",
        "source": {"url": f"{URL}#{row['imo']}-{row['date'].date().isoformat()}", "source": SOURCE,
                   "source_type": "official", "side": "neutral", "kind": "official",
                   "published_at": as_published, "title": f"IMO confirmed incident: {row['name']} (IMO {row['imo']})"},
    }


def collect(seen: dict, days: int = 30) -> list[dict]:
    """Confirmed incidents from the last `days` days not yet seen, as ready-made reports."""
    try:
        resp = requests.get(URL, headers={"User-Agent": USER_AGENT}, timeout=40)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("IMO incidents list unavailable: %s", exc)
        return []
    rows = parse(resp.text)
    cutoff = now_utc() - timedelta(days=days)
    stamp = iso(now_utc())
    reports = []
    for row in rows:
        key = f"imo:{row['imo']}:{row['date'].date().isoformat()}"
        if row["date"] < cutoff or key in seen:
            continue
        seen[key] = stamp
        reports.append(to_report(row, stamp))
    log.info("IMO list: %d rows, %d new in the last %d days", len(rows), len(reports), days)
    return reports

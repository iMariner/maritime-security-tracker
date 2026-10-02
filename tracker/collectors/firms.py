"""NASA FIRMS satellite fire detections (free MAP_KEY from firms.modaps.eosdis.nasa.gov/api/map_key).

Fires offshore become "signal" leads for verification. Fires in port areas are kept as
evidence and attached to matching incidents. Persistent hotspots (gas flares, platforms)
are ignored using a short history of where fires were seen.
"""
from __future__ import annotations

import csv
import io
from datetime import timedelta

import requests

from ..common import FIRMS_HISTORY_FILE, env, iso, load_yaml, log, now_utc, parse_dt, read_json, write_json

SENSORS = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT")


def point_in_polygon(lon: float, lat: float, poly: list) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def classify(lon: float, lat: float, cfg: dict) -> tuple[str, str] | None:
    """Return ("offshore", region) or ("port", port name), or None if neither."""
    for region, poly in cfg.get("offshore", {}).items():
        if point_in_polygon(lon, lat, poly):
            return "offshore", region
    for port, (w, s, e, n) in cfg.get("ports", {}).items():
        if w <= lon <= e and s <= lat <= n:
            return "port", port
    return None


def _cell(lat: float, lon: float) -> str:
    return f"{round(lat * 20) / 20:.2f},{round(lon * 20) / 20:.2f}"  # ~5 km grid


def collect() -> list[dict]:
    key = env("FIRMS_MAP_KEY")
    if not key:
        log.info("FIRMS: skipped (no FIRMS_MAP_KEY)")
        return []
    cfg = load_yaml("regions.yaml").get("firms", {})
    history = read_json(FIRMS_HISTORY_FILE, {})
    today = now_utc().date().isoformat()
    detections = []
    for area, bbox in cfg.get("bbox", {}).items():
        for sensor in SENSORS:
            url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{sensor}/{','.join(map(str, bbox))}/1"
            try:
                resp = requests.get(url, timeout=60)
                resp.raise_for_status()
            except requests.RequestException as exc:
                log.warning("FIRMS %s %s failed: %s", area, sensor, exc)
                continue
            for row in csv.DictReader(io.StringIO(resp.text)):
                try:
                    lat, lon = float(row["latitude"]), float(row["longitude"])
                except (KeyError, ValueError):
                    continue
                where = classify(lon, lat, cfg)
                if not where:
                    continue
                t = row.get("acq_time", "0000").zfill(4)
                when = parse_dt(f"{row.get('acq_date')}T{t[:2]}:{t[2:]}:00Z")
                detections.append({"lat": lat, "lon": lon, "time": iso(when) if when else None, "where": where,
                                   "frp": row.get("frp"), "sensor": sensor})

    # Update the hotspot history and drop cells seen on 3+ separate days in the last 10.
    cutoff = (now_utc() - timedelta(days=10)).date().isoformat()
    for d in detections:
        days = set(history.get(_cell(d["lat"], d["lon"]), [])) | {(d["time"] or today)[:10]}
        history[_cell(d["lat"], d["lon"])] = sorted(days)
    history = {c: [x for x in days if x >= cutoff] for c, days in history.items()}
    history = {c: days for c, days in history.items() if days}
    write_json(FIRMS_HISTORY_FILE, history)

    fresh, seen_cells = [], set()
    for d in detections:
        cell = _cell(d["lat"], d["lon"])
        if len(history.get(cell, [])) >= 3 or cell in seen_cells:
            continue
        seen_cells.add(cell)
        fresh.append(d)
    log.info("FIRMS: %d detections in watch areas, %d new after removing persistent hotspots", len(detections), len(fresh))
    return fresh

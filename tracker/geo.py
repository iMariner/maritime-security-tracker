"""Approximate positions for incidents whose reports name a place but give no coordinates.

Positions set here are marked `position_approx: true` and shown as approximate on the map.
Order matters: more specific places come before the regions that contain them.
"""
from __future__ import annotations

import re

PLACES = [
    # Black Sea and Sea of Azov
    (r"chornomorsk|черноморск|чорноморськ", 46.30, 30.66),
    (r"pivdennyi|yuzhne|южн|південн", 46.62, 31.03),
    (r"izmail|ізмаїл|измаил", 45.35, 28.84),
    (r"\breni\b|рені|рени", 45.45, 28.29),
    (r"odesa|odessa|одес", 46.49, 30.74),
    (r"mykolaiv|nikolaev|микола|никола", 46.97, 31.99),
    (r"novorossiysk|новоросс", 44.72, 37.79),
    (r"\bcpc\b|caspian pipeline|южная озереевка|yuzhnaya ozereyevka", 44.65, 37.85),
    (r"tuapse|туапсе", 44.10, 39.08),
    (r"taman|тамань|port kavkaz|порт кавказ", 45.20, 36.70),
    (r"kerch|керч", 45.33, 36.55),
    (r"sevastopol|севастопол", 44.62, 33.53),
    (r"feodosi|феодос", 45.04, 35.39),
    (r"constan[tț]a|констан", 44.17, 28.66),
    (r"bosphorus|bosporus|istanbul|босфор|стамбул", 41.20, 29.12),
    (r"sea of azov|азовськ|азовск", 46.10, 36.80),
    (r"danube|дунай", 45.30, 29.20),
    (r"crimea|крим|крым", 44.90, 33.60),
    # Strait of Hormuz, Gulf, Gulf of Oman
    (r"fujairah|фуджейр", 25.15, 56.45),
    (r"khor fakkan", 25.35, 56.40),
    (r"bandar abbas", 27.10, 56.25),
    (r"jask", 25.60, 57.80),
    (r"qeshm", 26.75, 55.90),
    (r"musandam|khasab", 26.30, 56.40),
    (r"ras al[- ]khaimah", 25.85, 55.95),
    (r"sohar", 24.45, 56.70),
    (r"muscat", 23.65, 58.65),
    (r"gulf of oman|оманск", 24.80, 58.20),
    (r"hormuz|ормуз", 26.55, 56.35),
]
REGION_CENTRES = {
    "Black Sea": (43.40, 34.50),
    "Sea of Azov": (46.10, 36.80),
    "Strait of Hormuz": (26.55, 56.35),
    "Persian Gulf": (26.80, 52.50),
    "Gulf of Oman": (24.80, 58.20),
    "Red Sea": (19.50, 39.50),
    "Gulf of Aden": (12.50, 47.50),
}
_COMPILED = [(re.compile(p, re.I), lat, lon) for p, lat, lon in PLACES]


def approximate(inc: dict) -> tuple[float, float] | None:
    """Best-guess position from the location text, then the summary, then the region centre."""
    for field in ("location_text", "summary"):
        text = inc.get(field) or ""
        for pattern, lat, lon in _COMPILED:
            if pattern.search(text):
                return lat, lon
    return REGION_CENTRES.get(inc.get("region") or "")


def fill_position(inc: dict) -> bool:
    """Give an incident without coordinates an approximate position. Returns True if it changed."""
    if inc.get("lat") is not None and inc.get("lon") is not None and not inc.get("position_approx"):
        return False
    point = approximate(inc)
    if not point or (inc.get("lat"), inc.get("lon")) == point:
        return False
    inc["lat"], inc["lon"], inc["position_approx"] = point[0], point[1], True
    return True


# Places that fix the region whatever the model wrote (Houthi attacks are Red Sea, not Hormuz).
REGION_RULES = [
    (re.compile(r"houthi|yemen|hodeidah|hudaydah|bab[- ]el[- ]mandeb|yanbu|jeddah|jizan|red sea|eritrea|port sudan", re.I), "Red Sea"),
    (re.compile(r"gulf of aden|\baden\b|djibouti|somali", re.I), "Gulf of Aden"),
]


def region_override(inc: dict) -> str | None:
    """Return a corrected region when the incident's own text clearly places it elsewhere."""
    # Only where it happened and who is said to be behind it: summaries often mention other, separate attacks.
    text = " ".join(str(inc.get(k) or "") for k in ("location_text", "attribution_claimed"))
    for pattern, region in REGION_RULES:
        if pattern.search(text):
            return region if region != inc.get("region") else None
    return None

"""Featured image (1200x630): two map panels (Black Sea; Red Sea and the Gulf) with the day's incidents
as numbered markers, and under each panel a numbered list saying which ship and where."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .common import USER_AGENT, log

W, H = 1200, 630
NAVY, SEA, WHITE, MUTED = (11, 37, 69), (230, 238, 245), (255, 255, 255), (150, 170, 190)
STATUS_COLOURS = {"confirmed": (200, 30, 45), "reported": (235, 120, 20), "claimed": (120, 120, 120)}
# English-labelled tiles (the standard OpenStreetMap style shows Cyrillic and Arabic place names)
TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"
GULF = {"Strait of Hormuz", "Persian Gulf", "Gulf of Oman"}
RED_SEA = {"Red Sea", "Gulf of Aden"}
BLACK_SEA = {"Black Sea", "Sea of Azov"}
# extent (lon_min, lat_min, lon_max, lat_max) chosen by which areas have incidents that day
EXTENT_BLACK_SEA = (27.5, 40.8, 42.0, 47.2)
EXTENT_GULF = (47.5, 22.0, 60.5, 30.5)
EXTENT_RED_SEA = (32.0, 10.5, 52.0, 30.0)
EXTENT_BOTH = (32.0, 10.5, 61.0, 31.0)
FONT_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]
FONT_PATHS_REG = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf"]


def _font(size: int, bold: bool = True):
    for p in FONT_PATHS if bold else FONT_PATHS_REG:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def label(incident: dict) -> str:
    """'KAZIMAH III (tanker), Strait of Hormuz' or 'General cargo ship (Liberia), Odesa region'."""
    name = incident.get("vessel_name")
    kind = (incident.get("vessel_type") or "").strip()
    if name:
        who = f"{name} ({kind})" if kind else name
    else:
        who = (kind[:1].upper() + kind[1:] + " ship") if kind else "Unnamed ship"
        if incident.get("flag"):
            who += f" ({incident['flag']})"
    place = (incident.get("location_text") or incident.get("region") or "").split(",")[0].strip()
    return f"{who}, {place}" if place else who


def _spread(points: list[tuple]) -> list[tuple]:
    """Markers at the same approximate position are fanned out so each number stays readable."""
    out, seen = [], {}
    for lon, lat, *rest in points:
        key = (round(lon, 1), round(lat, 1))
        n = seen.get(key, 0)
        seen[key] = n + 1
        out.append((lon, lat, n, *rest))
    return out


def _marker(d: ImageDraw.ImageDraw, x: float, y: float, number: int, colour) -> None:
    r = 15
    d.ellipse([x - r - 3, y - r - 3, x + r + 3, y + r + 3], fill=WHITE)
    d.ellipse([x - r, y - r, x + r, y + r], fill=colour)
    d.text((x, y), str(number), font=_font(17), fill=WHITE, anchor="mm")


def _map_panel(extent, points, size) -> Image.Image:
    """Map tiles via staticmap, numbered markers drawn on top; a plain panel if tiles are unavailable."""
    w, h = size
    img, to_px = None, None
    try:
        from staticmap import CircleMarker, StaticMap
        from staticmap.staticmap import _lat_to_y, _lon_to_x

        m = StaticMap(w, h, url_template=TILES, headers={"User-Agent": USER_AGENT})
        # invisible corner markers set the extent; staticmap fits the zoom around all markers
        for lon, lat in ((extent[0], extent[1]), (extent[2], extent[3])):
            m.add_marker(CircleMarker((lon, lat), "#00000000", 0))
        img = m.render().convert("RGB")
        to_px = lambda lon, lat: (m._x_to_px(_lon_to_x(lon, m.zoom)), m._y_to_px(_lat_to_y(lat, m.zoom)))
    except Exception as exc:
        log.warning("Map tiles unavailable, using plain panel: %s", exc)
    if img is None:
        img = Image.new("RGB", size, SEA)
        to_px = lambda lon, lat: ((lon - extent[0]) / (extent[2] - extent[0]) * w,
                                  (extent[3] - lat) / (extent[3] - extent[1]) * h)
    d = ImageDraw.Draw(img)
    for lon, lat, stack, number, colour in _spread(points):
        x, y = to_px(lon, lat)
        x, y = x + (0, 36, -36)[stack % 3], y + (stack // 3) * 36  # a small grid when stacked
        _marker(d, min(max(x, 20), w - 20), min(max(y, 20), h - 20), number, colour)
    if not points:
        d.rounded_rectangle([w / 2 - 150, h / 2 - 24, w / 2 + 150, h / 2 + 24], 10, fill=NAVY)
        d.text((w / 2, h / 2), "No attacks reported", font=_font(20), fill=WHITE, anchor="mm")
    return img


def render(day: datetime, incidents: list[dict], out: Path) -> Path:
    from .geo import approximate

    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    d.text((40, 26), "MARITIME SECURITY BRIEF", font=_font(34), fill=WHITE)
    d.text((40, 70), day.strftime("%-d %B %Y") + "  |  Black Sea, Red Sea and the Gulf", font=_font(21), fill=MUTED)
    d.text((W - 40, 30), "iMariners", font=_font(30), fill=WHITE, anchor="ra")
    x = W - 40
    for status in reversed(list(STATUS_COLOURS)):  # legend, right-aligned under the logo
        tw = d.textlength(status.capitalize(), font=_font(15, False))
        d.text((x, 76), status.capitalize(), font=_font(15, False), fill=WHITE, anchor="ra")
        d.ellipse([x - tw - 20, 77, x - tw - 8, 89], fill=STATUS_COLOURS[status])
        x -= tw + 36

    gulf_regions = GULF | RED_SEA
    in_gulf = {i.get("region") for i in incidents} & gulf_regions
    gulf_extent = (EXTENT_BOTH if in_gulf & GULF and in_gulf & RED_SEA else
                   EXTENT_RED_SEA if in_gulf & RED_SEA else EXTENT_GULF)
    gulf_title = ("Red Sea and the Gulf" if gulf_extent == EXTENT_BOTH else
                  "Red Sea and Gulf of Aden" if gulf_extent == EXTENT_RED_SEA else "Hormuz and the Gulf")
    panels = [("Black Sea", EXTENT_BLACK_SEA, BLACK_SEA), (gulf_title, gulf_extent, gulf_regions)]

    panel_w, panel_h, top = 550, 330, 112
    number = 0
    for idx, (title, extent, regions) in enumerate(panels):
        x0 = 40 + idx * (panel_w + 20)
        pts, lines = [], []
        for i in incidents:
            if i.get("region") not in regions:
                continue
            number += 1
            colour = STATUS_COLOURS.get(i.get("status"), MUTED)
            point = (i["lat"], i["lon"]) if i.get("lat") is not None else approximate(i)
            if point:
                pts.append((point[1], point[0], number, colour))
            lines.append((number, colour, label(i)))
        img.paste(_map_panel(extent, pts, (panel_w, panel_h)), (x0, top + 40))
        d.text((x0, top + 4), f"{title}: {len(lines)} incident{'s' if len(lines) != 1 else ''}", font=_font(21), fill=WHITE)
        y = top + 40 + panel_h + 14
        shown = lines if len(lines) <= 4 else lines[:3]
        for n, colour, text in shown:
            d.ellipse([x0, y, x0 + 22, y + 22], fill=colour)
            d.text((x0 + 11, y + 11), str(n), font=_font(13), fill=WHITE, anchor="mm")
            f = _font(16, False)
            while d.textlength(text, font=f) > panel_w - 34 and len(text) > 10:
                text = text[:-2].rstrip(" ,") + "…"
            d.text((x0 + 32, y + 2), text, font=f, fill=WHITE)
            y += 28
        if len(lines) > len(shown):
            d.text((x0 + 32, y + 2), f"and {len(lines) - len(shown)} more in the brief", font=_font(15, False), fill=MUTED)
        if not lines:
            d.text((x0, y + 2), "Nothing reported in the last 24 hours", font=_font(16, False), fill=MUTED)

    d.text((W - 40, H - 14), "Positions approximate unless reported  |  Map: Esri, HERE, Garmin, OpenStreetMap contributors",
           font=_font(12, False), fill=MUTED, anchor="rs")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    return out

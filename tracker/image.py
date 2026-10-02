"""Featured image (1200x630): two map panels (Black Sea, Hormuz) with the day's incidents marked."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .common import USER_AGENT, log

W, H = 1200, 630
NAVY, SEA, WHITE, MUTED = (11, 37, 69), (230, 238, 245), (255, 255, 255), (150, 170, 190)
STATUS_COLOURS = {"confirmed": (200, 30, 45), "reported": (235, 120, 20), "claimed": (120, 120, 120)}
PANELS = [
    ("Black Sea", (27.5, 40.8, 42.0, 47.2), {"Black Sea", "Sea of Azov"}),
    ("Red Sea and Gulf", (32.0, 11.0, 60.0, 30.0),
     {"Strait of Hormuz", "Persian Gulf", "Gulf of Oman", "Red Sea", "Gulf of Aden"}),
]
FONT_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]


def _font(size: int):
    for p in FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def _map_panel(bbox, points, size) -> Image.Image:
    """OpenStreetMap tiles via staticmap; falls back to a plain panel if tiles are unavailable."""
    w, h = size
    try:
        from staticmap import CircleMarker, StaticMap

        m = StaticMap(w, h, url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png", headers={"User-Agent": USER_AGENT})
        # Invisible corner markers set the extent; staticmap fits the zoom around all markers.
        for lon, lat in ((bbox[0], bbox[1]), (bbox[2], bbox[3])):
            m.add_marker(CircleMarker((lon, lat), "#00000000", 0))
        for lon, lat, colour in points:
            m.add_marker(CircleMarker((lon, lat), "white", 22))
            m.add_marker(CircleMarker((lon, lat), "#%02x%02x%02x" % colour, 16))
        return m.render().convert("RGB")
    except Exception as exc:
        log.warning("Map tiles unavailable, using plain panel: %s", exc)
        img = Image.new("RGB", size, SEA)
        d = ImageDraw.Draw(img)
        for lon, lat, colour in points:
            x = (lon - bbox[0]) / (bbox[2] - bbox[0]) * w
            y = (bbox[3] - lat) / (bbox[3] - bbox[1]) * h
            d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=colour, outline=WHITE, width=3)
        return img


def render(day: datetime, incidents: list[dict], out: Path) -> Path:
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    d.text((40, 28), "MARITIME SECURITY BRIEF", font=_font(34), fill=WHITE)
    d.text((40, 72), day.strftime("%-d %B %Y") + "  |  Black Sea, Red Sea and Gulf", font=_font(22), fill=MUTED)
    d.text((W - 40, 34), "iMariners", font=_font(30), fill=WHITE, anchor="ra")

    panel_w, panel_h, top = 550, 400, 130
    for idx, (title, bbox, regions) in enumerate(PANELS):
        from .geo import approximate

        pts = []
        for i in incidents:
            if i.get("region") not in regions:
                continue
            point = (i["lat"], i["lon"]) if i.get("lat") is not None else approximate(i)
            if point:
                pts.append((point[1], point[0], STATUS_COLOURS.get(i["status"], MUTED)))
        x0 = 40 + idx * (panel_w + 20)
        img.paste(_map_panel(bbox, pts, (panel_w, panel_h)), (x0, top))
        count = sum(1 for i in incidents if i.get("region") in regions)
        d.rectangle([x0, top, x0 + panel_w, top + 44], fill=NAVY)
        d.text((x0 + 12, top + 8), f"{title}: {count} incident{'s' if count != 1 else ''}", font=_font(22), fill=WHITE)

    x = 40
    for label, colour in STATUS_COLOURS.items():
        d.ellipse([x, 560, x + 18, 578], fill=colour)
        d.text((x + 26, 557), label.capitalize(), font=_font(20), fill=WHITE)
        x += 170
    d.text((W - 40, 572), "Positions approximate unless reported", font=_font(14), fill=MUTED, anchor="ra")
    d.text((W - 40, 592), "Map data © OpenStreetMap contributors", font=_font(14), fill=MUTED, anchor="ra")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    return out

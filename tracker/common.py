"""Shared paths, config loading, JSON storage and small helpers."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"
INCIDENTS_FILE = DATA / "incidents.json"
SEEN_FILE = DATA / "seen.json"
FIRMS_HISTORY_FILE = DATA / "firms_history.json"
BRIEFS_DIR = DATA / "briefs"

USER_AGENT = "maritime-security-tracker/1.0 (+https://imariners.com)"

# Statuses, weakest to strongest. "signal" (satellite/AIS only) and "rejected" are never published.
PUBLISHED_STATUSES = ("claimed", "reported", "confirmed")

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tracker")


def load_yaml(name: str) -> dict:
    with open(CONFIG / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def read_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")
    tmp.replace(path)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    from dateutil import parser

    try:
        dt = parser.isoparse(str(value))
    except (ValueError, OverflowError):
        try:
            dt = parser.parse(str(value))
        except (ValueError, OverflowError):
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def item_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        raise SystemExit(f"Missing required setting {name}. Add it under GitHub repo Settings > Secrets and variables > Actions.")
    return value


_DASHES = re.compile(r"\s*[—–]\s*")


def no_em_dash(text: str) -> str:
    """iMariners house style: no em or en dashes. Replace them with a comma."""
    if not text:
        return text
    return _DASHES.sub(", ", text)


def prune_seen(seen: dict, days: int = 21) -> dict:
    cutoff = now_utc() - timedelta(days=days)
    return {k: v for k, v in seen.items() if (parse_dt(v) or now_utc()) >= cutoff}

#!/usr/bin/env python3
"""Freshness watchdog for the living Maritime Attack Tracker, run by Hermes as a no_agent cron job twice a day.

The owner is often at sea with only Telegram, so a silent stall must be reported. It checks:
  - the public feed (GitHub Pages living-incidents.json) was rebuilt recently: collection and Pages are running;
  - data/living-evidence.json changed recently: the Hermes maritime-living-evidence job is still adding evidence;
  - https://imariners.com/maritime-attack-tracker/ still serves the tracker mount.
It prints one line per problem for Telegram and nothing when all is well. Public URLs only; uses GITHUB_TOKEN
for the commits call when it can find one (higher rate limit) and never prints it. Standard library only.
Test with TRACKER_WATCHDOG_DRY_RUN=1: also prints a line when all is well.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = "iMariner/maritime-security-tracker"
FEED = "https://imariner.github.io/maritime-security-tracker/living-incidents.json"
PAGE = "https://imariners.com/maritime-attack-tracker/"
HOME = Path(os.environ.get("HERMES_HOME", "/opt/data"))
FEED_MAX_AGE = timedelta(hours=8)        # collection is hourly, but GitHub's scheduler can run hours late
EVIDENCE_MAX_AGE = timedelta(hours=30)   # the evidence job runs every 6 hours; allow a few empty runs


def token() -> str:
    """Hermes strips provider keys from cron scripts, so fall back to its own .env file."""
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    env = HOME / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "GITHUB_TOKEN":
                return value.strip().strip('"').strip("'")
    return ""


def fetch(url: str, tok: str = "") -> bytes:
    headers = {"User-Agent": "imariners-tracker-watchdog", "Cache-Control": "no-cache"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as resp:
        return resp.read()


def parse_time(value: str | None) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else None


def age(hours: timedelta) -> str:
    total = int(hours.total_seconds() // 3600)
    return f"{total // 24} days" if total >= 48 else f"{total} hours"


def decide(now: datetime, feed_at: datetime | None, evidence_at: datetime | None, page_ok: bool | None) -> list[str]:
    """One Telegram line per problem; an empty list means all is well. None means that check could not run."""
    lines = []
    if feed_at is None:
        lines.append("⚠️ Attack tracker: the public feed could not be read, so its freshness is unknown.")
    elif now - feed_at > FEED_MAX_AGE:
        lines.append(f"⚠️ Attack tracker: the public feed was last rebuilt {age(now - feed_at)} ago. "
                     "Collection or the Pages deploy has stopped; check GitHub Actions.")
    if evidence_at is None:
        lines.append("⚠️ Attack tracker: could not read when evidence was last added.")
    elif now - evidence_at > EVIDENCE_MAX_AGE:
        lines.append(f"⚠️ Attack tracker: no new evidence for {age(now - evidence_at)}. "
                     "The Hermes job maritime-living-evidence may be failing; check its runs.")
    if page_ok is None:
        lines.append("⚠️ Attack tracker: imariners.com/maritime-attack-tracker/ could not be reached.")
    elif not page_ok:
        lines.append("⚠️ Attack tracker: imariners.com/maritime-attack-tracker/ no longer shows the tracker.")
    return lines


def main() -> int:
    now = datetime.now(timezone.utc)
    tok = token()
    try:
        feed_at = parse_time(json.loads(fetch(FEED)).get("generated_at"))
    except Exception:
        feed_at = None
    try:
        commits = json.loads(fetch(f"https://api.github.com/repos/{REPO}/commits?path=data/living-evidence.json&per_page=1", tok))
        evidence_at = parse_time(commits[0]["commit"]["committer"]["date"]) if commits else None
    except Exception:
        evidence_at = None
    try:
        page_ok = b"maritime-living-mount" in fetch(PAGE)
    except Exception:
        page_ok = None
    lines = decide(now, feed_at, evidence_at, page_ok)
    if lines:
        print("\n".join(lines))
    elif os.environ.get("TRACKER_WATCHDOG_DRY_RUN"):
        print(f"dry run: all fine (feed {feed_at:%d %b %H:%M}Z, evidence {evidence_at:%d %b %H:%M}Z), would stay silent")
    return 0


if __name__ == "__main__":
    sys.exit(main())

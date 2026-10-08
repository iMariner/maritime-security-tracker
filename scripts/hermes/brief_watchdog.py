#!/usr/bin/env python3
"""Morning watchdog for the Maritime Security Brief, run by Hermes as a no_agent cron job at 06:00 UTC.

The approval message normally goes out at about 05:10 UTC. If by 06:00 it has not:
  - no brief was built today      -> comment "/brief now" on issue 38 (builds and sends it, unchecked);
  - built but never sent          -> comment "/send <date>" with a warning (sends the draft as it is).
It prints one line for Telegram when it acted or could not check, and nothing on a normal day.
Acts at most once per day. Standard library only. Never prints the token.
Test with WATCHDOG_DRY_RUN=1: prints the decision and posts nothing.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = "iMariner/maritime-security-tracker"
ISSUE = 38
HOME = Path(os.environ.get("HERMES_HOME", "/opt/data"))


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


def api(method: str, path: str, tok: str, body: dict | None = None):
    req = urllib.request.Request(
        f"https://api.github.com{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                 "User-Agent": "imariners-brief-watchdog"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def brief_record(day: str, tok: str) -> dict | None:
    """Today's brief record, or None if no brief was built today."""
    try:
        meta = api("GET", f"/repos/{REPO}/contents/data/briefs/{day}.json", tok)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    import base64
    return json.loads(base64.b64decode(meta["content"]))


def decide(record: dict | None, day: str) -> tuple[str | None, str]:
    """(comment to post or None, message for Telegram)."""
    if record is None:
        return ("/brief now",
                "⚠️ No brief had been built by 06:00 UTC today. I have started it again; the approval message "
                "should arrive in about 10 minutes, without the editor check, so read it before publishing.")
    if not record.get("notified"):
        return (f"/send {day}\nwarning: Sent by the 06:00 watchdog: the morning checks did not finish, so read the draft carefully.",
                "⚠️ Today's brief was built but the approval message had not been sent by 06:00 UTC. "
                "I have asked the tracker to send it again; it should arrive in about 10 minutes.")
    return (None, "")


def main() -> int:
    now = datetime.now(timezone.utc)
    day = now.date().isoformat()
    marker = HOME / "scripts" / f".brief_watchdog_{day}"
    if marker.exists():
        return 0  # already acted today
    tok = token()
    if not tok:
        print("⚠️ Brief watchdog: no GITHUB_TOKEN found, so today's brief could not be checked.")
        return 0
    try:
        comment, message = decide(brief_record(day, tok), day)
        if os.environ.get("WATCHDOG_DRY_RUN"):  # test mode: report the decision, post nothing
            print(f"dry run for {day}: would post {comment!r}" if comment else f"dry run for {day}: all fine, would stay silent")
            return 0
        if comment:
            api("POST", f"/repos/{REPO}/issues/{ISSUE}/comments", tok, {"body": comment})
            marker.write_text(now.isoformat(), encoding="utf-8")
            print(message)
    except Exception as exc:  # report the kind of failure only, never the token or response body
        print(f"⚠️ Brief watchdog could not check today's brief ({type(exc).__name__}). "
              "If no approval message arrives, reply here and ask Hermes to check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

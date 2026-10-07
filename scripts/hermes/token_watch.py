#!/usr/bin/env python3
"""GitHub token expiry watch, run by Hermes as a no_agent cron job (profile default, daily, delivered to Telegram).

The brief stops the day Hermes's fine-grained GITHUB_TOKEN expires, and the owner is often at sea. GitHub returns
the token's expiry in the `github-authentication-token-expiration` header of every API call, so this checks the
token in each Hermes profile that holds one (default and maritime) and prints one Telegram line when:
  - a token expires in 14, 7, 3, 2 or 1 days, or today;
  - a token is rejected (expired or revoked: the brief has stopped);
  - the two profiles hold tokens with different expiry dates (renewed in one profile only).
Silent on every other day. Standard library only. Never prints the token.
Test with TOKEN_WATCH_DRY_RUN=1 to print the status even on a quiet day.
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("HERMES_ROOT", "/opt/data"))
PROFILES = {"default": ROOT / ".env", "maritime": ROOT / "profiles" / "maritime" / ".env"}
WARN_DAYS = {14, 7, 3, 2, 1, 0}
RENEW = ("Renew it: GitHub, Settings, Developer settings, Fine-grained tokens, repo "
         "iMariner/maritime-security-tracker with Issues read/write and Contents read, then paste it in "
         "Hermes Keys of BOTH profiles (default and maritime).")


def read_token(env: Path) -> str:
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "GITHUB_TOKEN":
            return value.strip().strip('"').strip("'")
    return ""


def expiry(tok: str) -> date | None | str:
    """The token's expiry date, None if it never expires, or "rejected" on a 401."""
    req = urllib.request.Request("https://api.github.com/repos/iMariner/maritime-security-tracker",
                                 headers={"Authorization": f"Bearer {tok}", "User-Agent": "imariners-token-watch",
                                          "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.headers.get("github-authentication-token-expiration")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return "rejected"
        raise
    return datetime.strptime(raw[:10], "%Y-%m-%d").date() if raw else None


def decide(found: dict, today: date) -> str:
    """found: profile -> expiry date, None (no expiry), "rejected" or "missing". Returns the Telegram text or ""."""
    problems = {}  # message -> profiles it applies to, so one renewal message covers both profiles
    for prof, exp in found.items():
        msg = None
        if exp == "rejected":
            msg = "🚨 The GitHub token{where} is rejected (expired or revoked). The daily brief has stopped."
        elif exp == "missing":
            msg = "⚠️ There is no GitHub token{where}."
        elif isinstance(exp, date) and (exp - today).days in WARN_DAYS:
            left = (exp - today).days
            when = "today" if left == 0 else f"in {left} day{'s' if left > 1 else ''} ({exp:%d %b})"
            msg = "⏰ The GitHub token{where} expires " + when + "."
        if msg:
            problems.setdefault(msg, []).append(prof)
    lines = []
    for msg, profs in problems.items():
        where = " in Hermes" if len(profs) == len(found) else " in Hermes profile " + " and ".join(profs)
        lines.append(msg.format(where=where) + " " + RENEW)
    dates = {e for e in found.values() if isinstance(e, date)}
    if len(dates) > 1:
        lines.append("⚠️ The two Hermes profiles hold GitHub tokens with different expiry dates ("
                     + ", ".join(f"{p} {e:%d %b}" for p, e in found.items() if isinstance(e, date))
                     + "): paste the newest token in both.")
    return "\n".join(lines)


def main() -> int:
    found = {}
    for prof, env in PROFILES.items():
        if prof != "default" and not env.parent.exists():
            continue
        tok = read_token(env)
        try:
            found[prof] = expiry(tok) if tok else "missing"
        except Exception as exc:  # network trouble: say so once, never the token
            print(f"⚠️ Token watch could not reach GitHub ({type(exc).__name__}); I will try again tomorrow.")
            return 0
    text = decide(found, datetime.now(timezone.utc).date())
    if text:
        print(text)
    elif os.environ.get("TOKEN_WATCH_DRY_RUN"):
        print("Token watch: all fine. " + ", ".join(f"{p}: {e}" for p, e in found.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Reports Hermes found on official sites (UKMTO, JMIC) that the tracker did not have.

Hermes opens a GitHub issue labelled `missed` with the official text. Each run reads those issues as
items from an official, neutral source; the issue is closed once the AI step has read it.
"""
from __future__ import annotations

import re

import requests

from .. import github_issues
from ..common import env, log

API = "https://api.github.com"


def collect() -> list[dict]:
    repo = env("GITHUB_REPOSITORY")
    if not repo or not env("GITHUB_TOKEN"):
        return []
    try:
        resp = requests.get(f"{API}/repos/{repo}/issues", headers=github_issues._headers(),
                            params={"labels": "missed", "state": "open", "per_page": 20}, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Could not read 'missed' issues: %s", exc)
        return []
    allowed = {u.strip().lower() for u in (env("VERIFIERS") or "").split(",") if u.strip()}
    items = []
    for issue in resp.json():
        if issue.get("author_association") != "OWNER" and issue["user"]["login"].lower() not in allowed:
            continue  # only the owner's account (Hermes uses its token) or listed verifiers
        body = issue.get("body") or ""
        source = re.search(r"^source_name:\s*(.+)$", body, re.M | re.I)
        url = re.search(r"^source_url:\s*(\S+)$", body, re.M | re.I)
        items.append({
            "id": f"missed:{issue['number']}",
            "url": url.group(1) if url else issue["html_url"],
            "source": (source.group(1).strip() if source else "UKMTO"),
            "source_type": "official", "side": "neutral", "kind": "official",
            "title": issue["title"], "text": body[:3000], "published_at": issue["created_at"],
            "require_region_term": False, "issue_number": issue["number"],
        })
    if items:
        log.info("Missed-report issues from Hermes: %d", len(items))
    return items


def close_read(items: list[dict], processed: set) -> None:
    for it in items:
        if it["id"] in processed:
            github_issues.close_issue(it["issue_number"], "Read by the tracker and added to the incident data.")

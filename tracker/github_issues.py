"""Open a GitHub issue for each incident that needs checking (Hermes or you answer with /verdict)."""
from __future__ import annotations

import requests

from .common import env, log

API = "https://api.github.com"


def _headers() -> dict:
    return {"Authorization": f"Bearer {env('GITHUB_TOKEN', required=True)}", "Accept": "application/vnd.github+json"}


def open_verification_issue(inc: dict) -> int | None:
    repo = env("GITHUB_REPOSITORY")
    if not repo or not env("GITHUB_TOKEN"):
        log.info("No GitHub context; skipping verification issue for %s", inc["id"])
        return None
    lines = [
        f"**{inc['id']}** · status `{inc['status']}` · region {inc.get('region')}",
        "",
        f"**What was reported:** {inc.get('summary')}",
        "",
        f"- Vessel: {inc.get('vessel_name') or 'unknown'} (IMO {inc.get('imo') or 'unknown'}, flag {inc.get('flag') or 'unknown'}, {inc.get('vessel_type') or 'type unknown'})",
        f"- When: {inc.get('date_utc') or 'unknown'}",
        f"- Where: {inc.get('location_text') or 'unknown'}" + (f" ({inc['lat']}, {inc['lon']})" if inc.get("lat") is not None else ""),
        f"- Attack type: {inc.get('attack_type') or 'unknown'}",
        f"- Conflicting accounts: {'yes' if inc.get('conflicting') else 'no'}",
        "",
        "**Sources so far:**",
        *[f"- [{s['source']}]({s['url']}) ({s.get('side')}, {s.get('kind')})" for s in inc.get("sources", [])],
        "",
        "---",
        "Reply with one comment starting with a verdict line. Only the repo owner and accounts in the "
        "`VERIFIERS` variable are accepted:",
        "```",
        "/verdict confirmed | reported | claimed | rejected",
        "vessel_name: ...      (optional corrections, one per line)",
        "imo: ...",
        "source: https://...   (evidence you used; repeatable)",
        "note: one line on why",
        "```",
    ]
    title = f"Verify {inc['id']}: {inc.get('vessel_name') or inc.get('attack_type') or 'possible incident'}, {inc.get('region')}"
    resp = requests.post(f"{API}/repos/{repo}/issues", headers=_headers(), timeout=30,
                         json={"title": title[:200], "body": "\n".join(lines), "labels": ["verify"]})
    if resp.status_code >= 300:
        log.warning("Could not open issue for %s: %s %s", inc["id"], resp.status_code, resp.text[:200])
        return None
    return resp.json()["number"]


def close_issue(number: int, comment: str) -> None:
    repo = env("GITHUB_REPOSITORY", required=True)
    requests.post(f"{API}/repos/{repo}/issues/{number}/comments", headers=_headers(), json={"body": comment}, timeout=30)
    requests.patch(f"{API}/repos/{repo}/issues/{number}", headers=_headers(), json={"state": "closed"}, timeout=30)

"""Apply `/verdict` comments on open verification issues.

Sweeps every open issue labelled `verify` and applies the newest `/verdict` comment from the repo owner
or a listed verifier (repo variable VERIFIERS). Sweeping, rather than handling only the comment that
triggered the run, matters: when several verdicts arrive at once GitHub cancels all but one queued run,
and the run that does go ahead must still apply the others. It also runs before every collection run.
"""
from __future__ import annotations

import re

import requests

from . import github_issues, incidents as store
from .common import env, iso, log, no_em_dash, now_utc

STATUSES = {"confirmed", "reported", "claimed", "rejected"}
EDITABLE = {"vessel_name", "imo", "flag", "vessel_type", "location_text", "attack_type", "damage", "casualties",
            "attribution_claimed", "summary", "date_utc"}
API = "https://api.github.com"


def parse(body: str) -> dict | None:
    lines = [ln.strip() for ln in body.strip().splitlines() if ln.strip()]
    if not lines:
        return None
    m = re.match(r"^/verdict\s+(\w+)", lines[0], re.I)
    if not m or m.group(1).lower() not in STATUSES:
        return None
    out = {"status": m.group(1).lower(), "fields": {}, "sources": [], "note": ""}
    for ln in lines[1:]:
        if ":" not in ln:
            continue
        key, value = (x.strip() for x in ln.split(":", 1))
        key = key.lower()
        if value.startswith("<"):
            continue  # an unfilled placeholder copied from the example layout
        if key == "source" and value.startswith("http"):
            out["sources"].append(value)
        elif key == "note":
            out["note"] = no_em_dash(value)
        elif key in EDITABLE and value:
            out["fields"][key] = no_em_dash(value)
    return out


def apply(inc: dict, verdict: dict, user: str, comment_url: str) -> None:
    inc.update(verdict["fields"])
    for url in verdict["sources"]:
        if url not in {s["url"] for s in inc["sources"]}:
            inc["sources"].append({"url": url, "source": "Verifier evidence", "source_type": "verification",
                                   "side": "neutral", "kind": "verification", "published_at": iso(now_utc()), "title": None})
    inc["verdict"] = {"status": verdict["status"], "by": user, "at": iso(now_utc()), "note": verdict["note"],
                      "comment_url": comment_url}
    if inc.get("status") != verdict["status"]:
        inc["status_changed_at"] = iso(now_utc())
    inc["status"] = verdict["status"]
    inc["last_updated"] = iso(now_utc())


def _get(path: str, **params):
    resp = requests.get(f"{API}{path}", headers=github_issues._headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def sweep() -> int:
    """Apply every pending verdict. Returns the number of issues closed."""
    repo = env("GITHUB_REPOSITORY")
    if not repo or not env("GITHUB_TOKEN"):
        log.info("No GitHub context; skipping verdict sweep")
        return 0
    allowed = {u.strip().lower() for u in (env("VERIFIERS") or "").split(",") if u.strip()}
    incidents = store.load()
    by_issue = {i.get("verification_issue"): i for i in incidents if i.get("verification_issue")}
    closed = 0
    for issue in _get(f"/repos/{repo}/issues", labels="verify", state="open", per_page=100):
        found = None
        for c in _get(f"/repos/{repo}/issues/{issue['number']}/comments", per_page=100):
            if c.get("author_association") != "OWNER" and c["user"]["login"].lower() not in allowed:
                continue
            parsed = parse(c.get("body") or "")
            if parsed:
                found = (parsed, c)  # comments come oldest first, so the newest valid verdict wins
        if not found:
            continue
        verdict, c = found
        inc = by_issue.get(issue["number"])
        if inc:
            apply(inc, verdict, c["user"]["login"], c["html_url"])
            store.save(incidents)
            msg = f"Applied: **{verdict['status']}** for {inc['id']}."
            log.info("%s set to %s by %s (issue #%d)", inc["id"], verdict["status"], c["user"]["login"], issue["number"])
        else:
            msg = "Closed: no incident is linked to this issue any more (the data was rebuilt)."
            log.warning("No incident linked to issue #%d; closing it", issue["number"])
        github_issues.close_issue(issue["number"], msg)
        closed += 1
    log.info("Verdict sweep: %d issue(s) closed", closed)
    return closed


if __name__ == "__main__":
    sweep()

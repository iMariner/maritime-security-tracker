"""Apply a `/verdict` comment on a verification issue (run by .github/workflows/verdict.yml).

Reads the GitHub event payload, checks the commenter is allowed, updates data/incidents.json
and closes the issue.
"""
from __future__ import annotations

import json
import re

from . import github_issues, incidents as store
from .common import env, iso, log, no_em_dash, now_utc

STATUSES = {"confirmed", "reported", "claimed", "rejected"}
EDITABLE = {"vessel_name", "imo", "flag", "vessel_type", "location_text", "attack_type", "damage", "casualties",
            "attribution_claimed", "summary", "date_utc"}


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
        if key == "source" and value.startswith("http"):
            out["sources"].append(value)
        elif key == "note":
            out["note"] = no_em_dash(value)
        elif key in EDITABLE and value:
            out["fields"][key] = no_em_dash(value)
    return out


def main() -> None:
    with open(env("GITHUB_EVENT_PATH", required=True), encoding="utf-8") as f:
        event = json.load(f)
    comment, issue = event["comment"], event["issue"]
    user = comment["user"]["login"]
    allowed = {u.strip().lower() for u in (env("VERIFIERS") or "").split(",") if u.strip()}
    if comment.get("author_association") != "OWNER" and user.lower() not in allowed:
        log.info("Ignoring comment from %s (not owner or listed verifier)", user)
        return
    verdict = parse(comment["body"])
    if not verdict:
        log.info("Comment is not a /verdict; nothing to do")
        return

    incidents = store.load()
    inc = next((i for i in incidents if i.get("verification_issue") == issue["number"]), None)
    if not inc:
        log.warning("No incident linked to issue #%d", issue["number"])
        return
    inc.update(verdict["fields"])
    for url in verdict["sources"]:
        if url not in {s["url"] for s in inc["sources"]}:
            inc["sources"].append({"url": url, "source": "Verifier evidence", "source_type": "verification",
                                   "side": "neutral", "kind": "verification", "published_at": iso(now_utc()), "title": None})
    inc["verdict"] = {"status": verdict["status"], "by": user, "at": iso(now_utc()), "note": verdict["note"],
                      "comment_url": comment["html_url"]}
    inc["status"] = verdict["status"]
    inc["last_updated"] = iso(now_utc())
    store.save(incidents)
    github_issues.close_issue(issue["number"], f"Applied: **{verdict['status']}** for {inc['id']}.")
    log.info("%s set to %s by %s", inc["id"], verdict["status"], user)


if __name__ == "__main__":
    main()

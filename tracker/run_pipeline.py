"""Collect -> pre-filter -> AI extract -> match/merge -> verification issues. Runs every 30 minutes.

  python -m tracker.run_pipeline             full run
  python -m tracker.run_pipeline --dry-run   collect + pre-filter only, print candidates, write nothing
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta

from . import github_issues, incidents as store, llm
from .collectors import firms, rss, telegram
from .common import SEEN_FILE, env, iso, log, now_utc, parse_dt, prune_seen, read_json, write_json
from .extract import extract
from .prefilter import is_candidate

MAX_AGE = timedelta(days=3)  # ignore posts older than this (first run, back-paging)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    seen = read_json(SEEN_FILE, {})
    items = telegram.collect(seen) + rss.collect(seen)
    fresh = [it for it in items if it["id"] not in seen]
    cutoff = now_utc() - MAX_AGE
    fresh = [it for it in fresh if (parse_dt(it.get("published_at")) or now_utc()) >= cutoff]
    candidates = [it for it in fresh if is_candidate(it)]
    # Newest first, so if the AI cap is hit the older items wait for the next run.
    candidates.sort(key=lambda it: parse_dt(it.get("published_at")) or now_utc(), reverse=True)
    candidate_ids = {it["id"] for it in candidates}
    max_items = int(env("MAX_LLM_ITEMS_PER_RUN") or (24 if llm.free_tier_only() else 60))
    log.info("Items: %d collected, %d new, %d pass keyword filter (AI cap %d)", len(items), len(fresh), len(candidates), max_items)

    if args.dry_run:
        for it in candidates:
            print(f"- [{it['source']}] {it['published_at']} {it['url']}\n  {(it['title'] + ' ' + it['text'])[:220].replace(chr(10), ' ')}")
        return

    incidents = store.load()
    stamp = iso(now_utc())

    ai_failed = False
    if candidates and llm.available():
        batch = candidates[:max_items]
        try:
            reports = extract(batch)
        except RuntimeError as exc:
            # Keep going so collection, satellite data and seen-markers are still saved; fail the run at the end.
            log.error("AI step failed, candidates kept for the next run: %s", exc)
            ai_failed, reports, batch = True, [], []
        new = updated = 0
        for rep in reports:
            _, is_new = store.merge(rep, incidents)
            new += is_new
            updated += not is_new
        log.info("Incidents: %d new, %d reports merged into existing", new, updated)
        processed = {it["id"] for it in batch}
        # Non-candidates are marked seen right away; candidates only once the AI has read them.
        for it in fresh:
            if it["id"] in processed or it["id"] not in candidate_ids:
                seen[it["id"]] = stamp
    else:
        if candidates:
            log.warning("No LLM configured; %d candidates left unprocessed for the next run", len(candidates))
        for it in fresh:
            if it["id"] not in candidate_ids:
                seen[it["id"]] = stamp

    for det in firms.collect():
        key = f"firms:{det['sensor']}:{det['lat']:.3f},{det['lon']:.3f}:{det['time']}"
        if key in seen:
            continue
        seen[key] = stamp
        store.add_firms_signal(det, incidents)

    max_issues = int(env("MAX_VERIFY_ISSUES_PER_RUN", "5"))
    for inc in [i for i in incidents if store.needs_verification(i)][:max_issues]:
        number = github_issues.open_verification_issue(inc)
        if number:
            inc["verification_issue"] = number
            log.info("Opened verification issue #%d for %s", number, inc["id"])

    store.save(incidents)
    write_json(SEEN_FILE, prune_seen(seen))
    if ai_failed:
        sys.exit("AI step did not run: check LLM_API_KEY and the provider's credit")


if __name__ == "__main__":
    main()

"""Collect -> pre-filter -> AI extract -> match/merge -> verification issues. Runs every 30 minutes.

  python -m tracker.run_pipeline             full run
  python -m tracker.run_pipeline --dry-run   collect + pre-filter only, print candidates, write nothing
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta

from . import geo, github_issues, incidents as store, llm
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

    # On rate-limited free models, let small batches build up between runs, but never hold an item over 3 hours.
    min_items = int(env("LLM_MIN_ITEMS") or 1)
    oldest = min((parse_dt(it.get("published_at")) or now_utc() for it in candidates), default=now_utc())
    if candidates and len(candidates) < min_items and now_utc() - oldest < timedelta(hours=3):
        log.info("Only %d candidates (< LLM_MIN_ITEMS=%d); waiting for more before calling the AI", len(candidates), min_items)
        candidates_ready = False
    else:
        candidates_ready = True

    ai_failed = False
    if candidates and candidates_ready and llm.available():
        batch = candidates[:max_items]
        new, updated, processed, failed = extract(batch, incidents)
        ai_failed = failed > 0 and not processed  # every batch failed
        log.info("Incidents: %d new, %d reports merged into existing", new, updated)
        # Non-candidates are marked seen right away; candidates only once the AI has read them.
        for it in fresh:
            if it["id"] in processed or it["id"] not in candidate_ids:
                seen[it["id"]] = stamp
    else:
        if candidates and not llm.available():
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

    # Re-apply the status rules to every incident, so a rule change takes effect on stored data too.
    # Also give incidents without coordinates an approximate position from the place they name.
    for inc in incidents:
        inc["status"] = store.compute_status(inc)
        geo.fill_position(inc)

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

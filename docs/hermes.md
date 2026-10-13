# Hermes agent: verification desk

Runs on the iMariners Hermes (`hermes7.splicerun.net`, on the Webyne VPS), in profile **`maritime`** (since 7 Oct 2026; see
`docs/hermes/README.md` for profiles, skills and memory), as the cron job `maritime-security-tracking`, daily at 04:30 UTC; it starts the morning chain by commenting `/brief`. Part A checks
UKMTO/JMIC coverage and files `missed` issues; Part B verifies up to 5 `verify` issues.

Needs:
- `GITHUB_TOKEN` in Hermes **Keys**: a fine-grained GitHub token owned by the **iMariner** account, limited to the
  repository `iMariner/maritime-security-tracker`, with **Issues: Read and write** and nothing else.
  Because the token belongs to the repo owner, its `/verdict` comments are accepted automatically.
- DeepSeek as the model (already set: `deepseek-flash`).
- Web browsing / search tools (built in).

The server has `python3` but no `gh` CLI, so the task calls the GitHub REST API from Python. The prompt
describes the calls in words: Hermes blocks cron prompts that contain a literal `curl` command with an
Authorization header (its `exfil_curl_auth_header` guard).

## Cron job prompt

The job's instructions are in [`docs/hermes/cron/maritime-security-tracking.txt`](hermes/cron/maritime-security-tracking.txt). The Hermes job itself
holds only the short loader in [`docs/hermes/cron/job-prompt-stub.txt`](hermes/cron/job-prompt-stub.txt), which downloads
that file at every run, so a pushed change applies from the next run.

## What happens next

`.github/workflows/verdict.yml` reads the comment, updates `data/incidents.json`, and closes the issue.
You can do the same yourself from the GitHub mobile app by posting a `/verdict` comment.


## Second job: `maritime-editor-check` (daily 05:00 UTC)

Reads the held draft (`data/review/<date>.json`) against the sources and comments `/review <date>` with fixes on
issue 38. `review.yml` applies them and rebuilds the draft, held for the final read (GitHub variable
`FINAL_READ=on`). If no check arrives, the 06:00 watchdog sends the draft with a warning.

The job's instructions are in [`docs/hermes/cron/maritime-editor-check.txt`](hermes/cron/maritime-editor-check.txt). The Hermes job itself
holds only the short loader in [`docs/hermes/cron/job-prompt-stub.txt`](hermes/cron/job-prompt-stub.txt), which downloads
that file at every run, so a pushed change applies from the next run.


## Third job: `maritime-final-read` (daily 05:25 UTC)

Reads the rebuilt draft against the checked facts and the editor's notes and comments `/send <date>` (with up to
three `warning:` lines for the approval message), or `/review <date>` with fixes and `send: yes` when it finds a
factual error. It never posts at 05:55 UTC or later, so it cannot race the watchdog.

The job's instructions are in [`docs/hermes/cron/maritime-final-read.txt`](hermes/cron/maritime-final-read.txt). The Hermes job itself
holds only the short loader in [`docs/hermes/cron/job-prompt-stub.txt`](hermes/cron/job-prompt-stub.txt), which downloads
that file at every run, so a pushed change applies from the next run.


## Fourth job: `maritime-weekly-learning` (Sundays 06:00 UTC)

Reads the week's learning log (each brief record's `fact_check_fixes` and `review`) and the current
`config/lessons.yaml`, then comments `/lessons` with the rewritten list. The writer, the fact-checker and the
duplicate review follow those lessons. The daily editor check also adds single lessons (`lesson: writing|facts = ...`)
and saves what it learns to its own Hermes skill.

The job's instructions are in [`docs/hermes/cron/maritime-weekly-learning.txt`](hermes/cron/maritime-weekly-learning.txt). The Hermes job itself
holds only the short loader in [`docs/hermes/cron/job-prompt-stub.txt`](hermes/cron/job-prompt-stub.txt), which downloads
that file at every run, so a pushed change applies from the next run.


## Skills attached to the jobs

- maritime-security-tracking: maritime-verify-desk (Hermes's own), grounded-citations
- maritime-editor-check: maritime-editor-check (Hermes's own), grounded-citations, maps
- maritime-final-read: maritime-editor-check, maritime-brief-system
- maritime-weekly-learning: maritime-editor-check

Plugins installed and enabled (Hermes catalog, pinned commits): hermes-cron (cron operating skill), reaction-feedback
(Telegram 👍/👎 reach the agent), telegram_dashboard_probe (pinned health message, needs the Telegram channel) and
tokenwatch (daily scope, warns at 80% and 95% of 3,000,000 tokens, freeze_on_limit false: it never stops a job).
The money warning itself is the DeepSeek balance line in the daily Telegram message (below $3). Web search and page reading use Hermes's built-in
keyless provider rotation (Exa, Parallel, Firecrawl, Keenable); no key is set.

## Telegram channel and the feedback skill

Hermes has its own Telegram bot (manual BotFather setup, allowed user 5871106546). The pinned health message comes
from `telegram_dashboard_probe` (settings: chat_id 5871106546, period 300 s, limits lines off, Asia/Kolkata). The plugin
only picked the chat up from the custom key HERMES_DASHBOARD_PROBE_CHAT in Keys (.env), not from config.yaml settings.
Restarting: the dashboard's Restart Gateway buttons did not restart the messaging gateway; ask Hermes in Chat to run
`hermes gateway restart` (s6-supervised), then check the logs.
Hermes skill `maritime-brief-feedback` (category maritime): when the publisher reacts or replies about a brief,
Hermes checks the claim against the sources, then comments `/review <date>` on issue 38 with fix lines and/or
`lesson:` lines. The tracker applies them, rebuilds the brief and sends a fresh approval message. A thumbs up is
noted; a bare thumbs down gets one question back. Hermes never publishes or posts anywhere itself.

## DeepSeek balance alert in the Hermes chat

Hermes job `deepseek-balance-alert` (no_agent, script `/opt/data/scripts/deepseek_balance.py`, daily 05:20 UTC,
delivered to Telegram). Silent while the balance is at or above BALANCE_WARN_USD (default 3); below it, one
warning line to top up. Hermes strips provider keys from cron script environments, so the script reads
DEEPSEEK_API_KEY from the environment first, then from $HERMES_HOME/.env. Read-only balance call; costs nothing.
The daily approval message (n8n bot) also shows the balance on its first line.

## Morning watchdog (Hermes job `maritime-brief-watchdog`, 06:00 UTC)

no_agent script `/opt/data/scripts/brief_watchdog.py` (source: `scripts/hermes/brief_watchdog.py` in this repo;
Hermes copies it unchanged). If today's brief record does not exist by 06:00 UTC it comments `/brief now` on #38
(brief-trigger dispatches the brief without waiting for the editor check); if it exists but was never sent, it
comments `/send <date>` with a warning line, which sends the draft as it is. It also checks that the four job
instruction files in `docs/hermes/cron/` end with their END line and says so on Telegram if one does not. It tells the owner on Telegram when it acts or
cannot check, acts at most once a day (marker file), and is silent on a normal day. Test with WATCHDOG_DRY_RUN=1.
To update the script: change it here, then ask Hermes to re-download it to /opt/data/scripts/.

## Queue rules (GitHub Actions)

verdict, review and refresh-image hold the `data-writer` slot at job level, so runs started by unrelated comments
do not take or cancel it. Collection has its own queue, skips 04:00-05:59 UTC, and gives way on a data race; the
brief, review, verdict and refresh commits win a race (`git pull --rebase -X theirs`).

## Hermes knowledge skill

Hermes skill `maritime-brief-system` (category maritime, created 7 Oct 2026) summarises this system and tells Hermes to read
`docs/RUNBOOK.md` and this file from GitHub before answering questions about it. Update the skill when the runbook
changes in a way Hermes must know (schedules, commands, rules).

# iMariners Maritime Security Brief: system runbook

The one document to read first, months from now. It says what this system is, why it was built this way, how
every part works, how to operate and repair it, and what was decided along the way. Last full update: 7 October 2026.
Detailed prompts for the Hermes jobs are in [hermes.md](hermes.md); server setup history is in
[DEPLOY-ON-TEST-SERVER.md](DEPLOY-ON-TEST-SERVER.md).

## 1. What it is and why

Every morning the system publishes a short, verified news brief on **imariners.com** about attacks on merchant ships in
the war-risk areas: **Black Sea (and Sea of Azov), Red Sea and Gulf of Aden, Strait of Hormuz, Gulf of Oman and the
Persian Gulf**. It is written for seafarers on board and ship managers ashore.

Owner's requirements that shaped everything:
- **Runs unattended for weeks**, because the owner sails and only has **Telegram** on board. One tap (Publish or
  Skip) is the only daily human step.
- **Cheap.** No profit in it. AI is **DeepSeek** (paid API, cents per day); compute is free GitHub Actions on a
  public repo; Hermes and n8n run on the owner's own server (Webyne VPS, managed through SpliceRun).
- **Accurate before fast.** Official sources first (UKMTO, JMIC, IMO, MARAD), then news and public Telegram channels
  from both sides of each conflict. Claims stay claims. Nothing is published without the owner's tap.
- **News-article style**, British English, no em dashes, short paragraphs, a "Key points" card, a map, sources.
- The tweet is posted **manually** by the owner from Telegram (the X API is paid); an X helper page opens the X app.

## 2. The parts and where they live

| Part | Where | What it does |
|---|---|---|
| Tracker code | GitHub `iMariner/maritime-security-tracker` (public), local copy `~/Developer/maritime-security-tracker` | Python package `tracker/`: collects, extracts with DeepSeek, merges incidents, writes the brief, publishes a WordPress draft, notifies n8n |
| GitHub Actions | `.github/workflows/` | Free compute and the scheduler of last resort |
| Hermes Agent | `https://hermes7.splicerun.net` (open via app.splicerun.com, instance "Hermes Agent", button "Open Hermes Agent") | Verifies incidents, starts the brief, checks the draft against sources, learns lessons, watchdog, balance alert, Telegram chat with the owner |
| n8n | `https://task7.splicerun.net`, workflow "Maritime Security Brief: approve, publish, tweet" (id `SOkXGQwtDOuWiHiz`) | Sends the approval message on Telegram, publishes on WordPress when the owner taps Publish, sends the tweet helper link |
| WordPress | imariners.com, category **Maritime Security** (id 315, `/category/news/maritime-security/`), author **iMariners Security Desk** (user `security-desk`, id 747) | The published briefs; homepage shows the latest 4 in a "Watch log" (excluded from "New guides") |
| Preview and dashboard | GitHub Pages `https://imariner.github.io/maritime-security-tracker/` (`/preview/<date>.html`, `x.html`) | Draft preview linked from Telegram; map dashboard; X helper |
| Telegram bots | Approval bot (n8n) and **@SpliceRun_Hermes_bot** (Hermes) | Approval message comes from the n8n bot; feedback, warnings and the pinned health message come from the Hermes bot |

## 3. A normal day (times UTC; India is UTC+5:30)

| Time | Who | What |
|---|---|---|
| hourly at :37 (not 04:00-05:59) | GitHub `collect.yml` | Collect Telegram channels, RSS/Google News, IMO list, Hermes "missed" reports; DeepSeek extracts incidents; merge into `data/incidents.json`; open `verify` issues |
| 04:30 | Hermes `maritime-security-tracking` | Read UKMTO/JMIC, open `missed` issues for official reports we lack, decide up to 5 `verify` issues with `/verdict` comments, then comment `/brief` on pinned issue **#38** |
| ~04:35 | GitHub `brief-trigger.yml` then `daily-brief.yml` (hold) | Fresh collection, select the last 24 h, DeepSeek writes the article, a second DeepSeek pass fact-checks it, map image, WordPress **draft**, preview page; writes `data/review/<date>.json`; **does not notify yet** |
| 05:00 | Hermes `maritime-editor-check` | Opens the sources, checks ship names, dates, duplicates, status, positions; comments `/review <date>` with fix lines and lessons on #38 |
| ~05:10 | GitHub `review.yml` then `daily-brief.yml` (reviewed, held) | Apply fixes, rebuild the same draft with **only the incidents the editor saw** (news collected later waits for tomorrow), code consistency checks (an area called quiet that has an incident is removed; a ship in the data missing from the text is flagged), hold |
| 05:25 | Hermes `maritime-final-read` (active when the GitHub variable `FINAL_READ=on`; otherwise the editor-check rebuild is sent straight away) | Reads the rebuilt draft; comments `/send <date>` (with optional `warning:` lines) or one last `/review ... send: yes` |
| ~05:30 | GitHub `daily-brief.yml` (send) | **Send the approval message** via n8n (11:00 IST) |
| 05:20 | Hermes `deepseek-balance-alert` | Silent unless the DeepSeek balance is below $3 |
| 05:40 | Hermes `github-token-watch` (profile default, script `scripts/hermes/token_watch.py`) | Silent unless the GitHub token in either profile expires within 14 days (warns at 14, 7, 3, 2, 1, 0), is rejected, or the two profiles differ |
| 06:00 | Hermes `maritime-brief-watchdog` | Silent unless no approval message went out; then it repairs (see section 6) and tells the owner |
| 06:10, 06:40, 07:25, 07:55 | GitHub `daily-brief.yml` schedule | Backups only: build and send if nothing exists, or send a built-but-unsent draft with a warning |
| owner's tap | n8n | Publish: post goes live, done message with the X helper link. Skip: nothing. No answer in 6 h: approval cancelled, post stays a draft |
| Sunday 06:00 | Hermes `maritime-weekly-learning` | Rewrites the lessons list from the week's mistakes |

The approval message shows: DeepSeek balance, editor-check result, quality checklist, fact-check count, preview link
and the tweet text. Lines starting with ⚠️ mean "read the draft before publishing".

## 4. How the tracker decides what is true

- **Status ladder**: `signal` (satellite or weak lead), `claimed` (one side only), `reported` (independent media with
  their own evidence), `confirmed` (a *named* neutral authority such as UKMTO, JMIC, MARAD, IMO, a coast guard, the
  owner or flag state, or a Hermes verdict), `rejected`, `merged`. Words like "maritime authority" or "shipping
  sources" never count as confirmation.
- **Duplicates**: an AI review pass groups reports of the same attack, with hard code rules on top (attack dates within
  two days, never merge different flags or different numbered sisters like KAZIMAH II/III, official records keep their
  summary). Unnamed reports near an official IMO record, and one-outlet retellings of a Hermes-confirmed attack in a
  neighbouring area (Red Sea / Gulf of Aden, Hormuz / Gulf of Oman / Gulf) are folded in as sources.
- **Map**: numbered markers with a ship list; no dot when a report names only a whole sea ("position not reported").
- **Context**: "Nth merchant ship in seven days" counts only incidents that name a ship, flag, IMO or type.
- **Article shape**: one story per headline; no fact told twice (key points summarise, sections add detail); attacks
  older than 48 hours with no one hurt get one "Earlier in the week" line; "What crews should know" gives the
  week-on-week trend per area (this 7 days vs the 7 before) and where today's attacks happened, never invented advice.
- **Public sources**: the article's Sources list shows only official bodies and outlets on
  `config/trusted_outlets.yaml` (max 4 per incident); partisan, local and aggregator sources are read but not shown.
  An incident with no trusted outlet says "local and social media reports, not yet confirmed by a major outlet".
  Add an outlet to that file when it has earned it.
- **Lessons** (`config/lessons.yaml`): rules every writer, fact-check and duplicate review must follow. Hermes adds
  lessons when it finds a repeatable mistake and rewrites the list weekly (max 25 per section).

## 5. Credentials (names only; values are never in the repo)

| Name | Where | Used for | Expires? |
|---|---|---|---|
| `LLM_API_KEY` | GitHub secret | DeepSeek for collection and writing | No, but the balance must stay above $0 |
| `WP_USER`, `WP_APP_PASSWORD` | GitHub secrets | WordPress draft and image upload (user `security-desk`) | Only if revoked |
| `N8N_WEBHOOK_URL`, `N8N_WEBHOOK_TOKEN` | GitHub secrets | Calling the n8n approval workflow (header `X-Tracker-Token`) | No |
| `GITHUB_TOKEN` (fine-grained PAT) | Hermes Keys in **both** profiles: `default` (`/opt/data/.env`) and `maritime` (`/opt/data/profiles/maritime/.env`) | Hermes comments on issues and reads the repo | **Yes: check its expiry date in GitHub before long trips** |
| `DEEPSEEK_API_KEY` | Hermes Keys | Hermes's own model and the balance alert | No |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS` (5871106546) | Hermes Channels | @SpliceRun_Hermes_bot | Only if revoked |
| `HERMES_DASHBOARD_PROBE_CHAT` | Hermes Keys (custom key) | Pinned health message chat | No |
| WordPress credential, Telegram credential, Header Auth | n8n Credentials | Publish, approval message, webhook auth | Only if revoked |
| GitHub variables | `LLM_BASE_URL`, `LLM_MODEL_FAST`, `LLM_MODEL_BRIEF` (deepseek-chat), `PUBLISH_MODE=draft`, `WP_CATEGORY_ID=315`, `WP_URL` | | |

## 6. Safety nets

- **Queue rules**: only real work holds the GitHub `data-writer` queue (job-level concurrency); collection has its own
  queue, pauses 04:00-05:59 UTC and gives way on a data race; brief/review/verdict commits win races.
- **Watchdog** (06:00 UTC, Hermes, no AI cost): no brief built -> comments `/brief now` (built and sent without the
  editor check); built but not sent -> comments `/send <date>` with a warning (sent as it is). Tells the owner.
- **Frozen snapshot and consistency checks**: the rebuild after the editor check uses only the incidents it checked;
  code removes sentences that call an area quiet when it has an incident and flags ships missing from the text.
- **Final read** (05:25, Hermes): reads the draft that will actually be sent.
- **n8n failures**: the approval message is retried three times; if n8n still refuses, the run fails and the brief
  is not marked as sent, so the watchdog or a backup run sends it later.
- **Skipped briefs**: if a day's post never went live (Skip or no answer), its incidents are carried into the next
  brief instead of being treated as already reported (the tracker checks WordPress).
- **Publish without n8n**: ask the Hermes bot "publish today's brief"; it comments `/publish <date>` and GitHub
  publishes the draft directly (`publish.yml`).
- **Backup schedule** on GitHub (06:10 to 07:55 UTC, often hours late): builds or sends with a warning.
- **Quality checklist and ⚠️ lines** in the approval message; nothing publishes without the owner's tap.
- **Balance**: shown daily in the approval message; Hermes warns below $3; nothing stops before $0.
- **Health**: pinned message in the Hermes chat (gateway, Telegram, cron jobs); `tokenwatch` warns at 80%/95% of
  3,000,000 tokens a day and never stops anything.
- **Feedback**: reply or react to @SpliceRun_Hermes_bot about a brief; the `maritime-brief-feedback` skill checks the
  claim against sources and posts fixes or lessons via `/review`.

## 7. How to do common things

| Task | How |
|---|---|
| Resend today's approval message | Comment `/send YYYY-MM-DD` on issue #38 as the owner, or ask Hermes on Telegram |
| Rebuild with fixes and send | `/review YYYY-MM-DD`, fix lines, last line `send: yes` (without it the rebuild waits for the final read) |
| Publish when n8n is down | Ask the Hermes bot "publish today's brief", or comment `/publish YYYY-MM-DD` on #38 |
| Start today's brief if nothing exists | Comment `/brief now` on #38, or run "Daily brief" in GitHub Actions |
| Build without sending (test) | Run "Daily brief" with `notify` off, or `preview` on (no WordPress) |
| Fix a published post's map | Run "Refresh brief map" with the date |
| Correct a fact | `/review <date>` lines: `merge:`, `name:`, `flag:`, `imo:`, `date:`, `position:`, `status:`, `note:`, `lesson:` (format in `tracker/review.py`). `note:` lines go to the writer and fact-checker on the rebuild and overrule the data (use them for a wrong credit, a detail in the wrong paragraph, conflicting dates); a second `/review` the same day adds to the first |
| Change the lessons | Edit `config/lessons.yaml`, or comment `/lessons` with `writing:` and `facts:` sections |
| Check the DeepSeek balance | GitHub Actions "Check DeepSeek balance", or the first line of the approval message |
| Change a Hermes prompt | Hermes, Cron, Edit job; keep `docs/hermes.md` and `docs/hermes/` (skills, memory, profiles) in step |
| Update the watchdog script | Edit `scripts/hermes/brief_watchdog.py`, push, ask Hermes to re-download it to `/opt/data/scripts/` |
| Restart Hermes's Telegram side | Ask Hermes in its Chat page to run `hermes gateway restart` (the dashboard Restart buttons did not restart it) |
| Hermes page says "Access ended" | Open app.splicerun.com, Hermes Agent instance, "Open Hermes Agent" again |
| Pause everything | Disable the GitHub workflows "Collect and process" and "Daily brief", pause the three jobs in Hermes profile `maritime` and `maritime-brief-watchdog` in `default` |

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No approval message by 11:30 IST | Hermes job failed, a run was cancelled, or n8n is down | The 06:00 watchdog repairs it; otherwise comment `/brief now` or `/send <date>` on #38; if n8n is down, publish with `/publish <date>` |
| Daily brief run failed at "Send to n8n" with HTTP 500 | n8n (task7) or its database is down (8 Oct: "could not open file ... I/O error") | Fix n8n on the server (SpliceRun), then `/send <date>`; meanwhile `/publish <date>` |
| "⚠️ Editor check did not run" | Hermes editor job failed or was late | Read the draft carefully; check Hermes Cron and Logs |
| Hermes stopped posting to GitHub | `GITHUB_TOKEN` expired or lost access | Create a new fine-grained token (repo iMariner/maritime-security-tracker: issues read/write, contents read) and paste it in Hermes Keys of **both** profiles (`default` and `maritime`) |
| Brief text wrong, map wrong | Thin sources or a missing rule | Reply to the Hermes bot; it fixes via `/review` and adds a lesson |
| DeepSeek errors, runs failing | Balance at $0 | Top up at platform.deepseek.com |
| Telegram buttons do nothing | n8n workflow inactive or "Approve within chat" turned on (needs a Telegram trigger) | Keep it off; check n8n Executions |
| Duplicated incidents | AI review missed it | `/review <date>` with `merge:`; the rule may become a lesson |
| Hermes timezone warning "Asia/Calcutta" | Invalid name; jobs fall back to UTC | Leave it: all schedules assume UTC; changing it would shift every job |

## 9. Decisions and rejected options

- **Claude API**: not used (cost; DeepSeek is enough with rules plus checks). GitHub Models returned junk; free
  OpenRouter models failed on JSON; `deepseek-v4-pro` returned empty output.
- **X API**: not used (paid); manual tweet via the X helper page. LinkedIn dropped.
- **UKMTO website/API**: blocked by Cloudflare for scripts; never bypassed. Hermes reads it in its own browser.
- **GitHub schedule alone**: too unreliable (6+ hours late), so Hermes starts the chain and GitHub is the backup.
- **Approve within chat** in n8n: does not work without a Telegram trigger; turned off, buttons are links.
- **web-defuddle, blocked-page-recovery plugins, X search**: not needed or against the no-bypass rule.
- **tokenwatch freeze**: off; the owner wants everything to run until the balance reaches $0.

## 10. History

- **2 Oct 2026**: initial build: collectors, DeepSeek extraction, review pass, brief, WordPress, n8n approval, X helper,
  Security Desk author, category, homepage watch log and STCW banner. Fixed 9 duplicate Hormuz incidents, Kazimah vs
  KAZIMAH III, over-merging rules.
- **3 Oct**: GitHub schedule found 6 h late; brief collects fresh data itself; backup times.
- **4 Oct**: Hermes `/brief` trigger on issue #38; map redesigned (numbered markers, English labels); no dot for whole-sea
  reports; "Refresh brief map" workflow.
- **5 Oct**: false "confirmed" from "Maritime Authority" fixed; echo absorption; LIPSI identified; editor check
  (`/review`), news-style writing rules, lessons loop and weekly learning; Hermes skills attached; plugins
  (hermes-cron, reaction-feedback, telegram_dashboard_probe, tokenwatch); Hermes Telegram bot and feedback skill;
  DeepSeek balance line and alert; collection hourly; homepage "New guides" excludes briefs.
- **6 Oct**: first fully automatic morning (sent 05:10 UTC).
- **7 Oct**: queue race fixed (job-level concurrency, collection's own queue and quiet window, commits win races),
  skipped backup runs no longer fail, `/brief now`, 06:00 watchdog. Editor `note:` lines now reach the writer and
  survive a later `/review`; article shape rules and the trusted public source list (after the On Peace mis-credit).
  Hermes split into profiles: `maritime` runs the three AI jobs with its own memory and skills, `default` keeps
  Telegram, the watchdog, the balance alert, SIRE and sea areas (see `docs/hermes/README.md`).
  `blocked-page-recovery` skill disabled.
- **8 Oct**: the Qatar tanker strike (UKMTO, casualties) was hidden inside the older On Peace record and the rebuilt
  draft called the Gulf quiet; n8n's database failed (HTTP 500). Added `unmerge:`, frozen rebuild snapshot, code
  consistency checks, the 05:25 Hermes final read (`/send`), n8n retries without a false "sent" mark, and the
  `/publish` fallback that does not need n8n.

## 11. Costs (October 2026)

DeepSeek: collection (hourly) is the main cost; the brief and fact-check are a few cents a day; Hermes runs on
deepseek-flash at about 1-3 cents per job. GitHub Actions and Pages: free (public repo). Server: the owner's VPS.

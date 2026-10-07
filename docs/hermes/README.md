# Hermes configuration for the brief (source of truth)

The live Hermes (hermes7.splicerun.net, v0.21.5) should match these files. Change them here first, then apply.

| File | Goes to |
|---|---|
| `skills/maritime-brief-system/SKILL.md` | skill `maritime-brief-system` (operating manual; Telegram questions) |
| `skills/maritime-brief-feedback/SKILL.md` | skill `maritime-brief-feedback` (owner feedback to `/review`) |
| `skills/maritime-editor-check/ADDENDUM.md` | appended to skill `maritime-editor-check` (the job also writes to this skill itself) |
| `cron/maritime-editor-check.txt` | prompt of cron job `maritime-editor-check` |
| `MEMORY.maritime.md` | `memories/MEMORY.md` of the profile that runs the maritime jobs (limit 2200 chars, entries split by `§`) |
| `USER.maritime.md` | `memories/USER.md` of that profile (limit 1375 chars) |

Disabled on purpose: skill `blocked-page-recovery` (gets round bot walls; against the no-bypass rule).

## Profiles

Hermes runs every profile from one gateway (`gateway.multiplex_profiles: true`, already on). Each profile has its
own `.env` keys, memory (2200 chars), skills and cron jobs. Each Telegram bot token can belong to one profile only.

| Profile | Runs | Telegram |
|---|---|---|
| `maritime` | maritime-security-tracking, maritime-editor-check, maritime-weekly-learning (all deliver `local`) | none |
| `default` | Telegram chat (feedback skill, manual skill), maritime-brief-watchdog, deepseek-balance-alert (scripts that report to Telegram), sire-card-improvement, sea-areas-watch, sea-areas-advisories | @SpliceRun_Hermes_bot |

Why: the 2200-char memory and the skill list were shared by the brief, SIRE and sea-areas jobs, so lessons from
one could crowd out or leak into another, and every brief job carried 68 skills in its prompt. The maritime
profile carries only maritime-verify-desk, maritime-editor-check, grounded-citations, maps and maritime-brief-system.

**GITHUB_TOKEN lives in both profiles' Keys.** Renew it in both (`default` for the watchdog and feedback,
`maritime` for the jobs).

## Status (7 Oct 2026)

Applied: skills, editor-check prompt, memory in both profiles, profile `maritime` (config and keys cloned from
`default`, Telegram plugins disabled there), the three jobs moved, old copies paused in `default` (delete them
after a week of good mornings). Not done: switching off the ~57 general skills `maritime` inherited (the jobs only
load their attached skills, so this is tidiness and prompt size, not correctness).

## Applying a move safely

1. Create profile `maritime`, cloning config from `default` (copies config and keys on the server).
2. Copy the five skills into it; write its MEMORY.md and USER.md.
3. Create the three jobs in `maritime` with the same schedules, prompts and skills; check they show the next run.
4. Pause (do not delete) the three old jobs in `default`. Delete them after a week of good mornings.
5. The 06:00 watchdog in `default` and the GitHub backup schedule still cover a morning the new jobs miss.

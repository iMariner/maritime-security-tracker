# Deploy the Maritime Security Tracker on the SpliceRun test server

**For:** the agent or person setting this up on the SpliceRun test server (n8n + Hermes already installed).
**Code:** `~/Developer/maritime-security-tracker` on Ajit's Mac (not yet on GitHub).
**Written:** 2 October 2026.

This is a self-contained work order. Do the phases in order. Each phase ends with a check that must pass
before moving on. Anything marked **ASK** needs Ajit's decision or credentials; do not guess those.

---

## 0. What is being built (read first)

A daily **Maritime Security Brief** on attacks against ships in the Black Sea, the Red Sea and the Gulf,
published on imariners.com and shared on X and LinkedIn.

| Part | Runs on | Job |
|---|---|---|
| GitHub Actions (public repo) | GitHub, free | hourly: read Telegram channels, news, NASA fire data; DeepSeek extracts incidents; stores `data/incidents.json`; opens `verify` issues for doubtful ones. Daily after Hermes's 04:30 UTC check (backup schedule from 06:10): collects fresh news, writes the brief and creates the WordPress draft |
| **n8n** | **test server** | receives the brief from GitHub, asks Ajit on Telegram (Publish / Skip), publishes the WordPress post, posts to X and LinkedIn, reports back |
| **Hermes** | **test server** | every 2 to 3 hours: works the `verify` issues on GitHub and answers each with a `/verdict` comment |
| imariners.com | WordPress | the published brief, in category `maritime-security` |
| GitHub Pages | GitHub, free | public incident map |

The AI provider is **DeepSeek** (OpenAI-compatible API). Ajit is often at sea, so nothing must depend
on his laptop being online.

Already done and tested locally: collectors (live run read 302 Telegram posts and 363 news items),
keyword filter, incident matching, map image, dashboard, 8 unit tests passing.
**Not yet tested:** DeepSeek calls, WordPress publishing, the n8n workflow import, Hermes verification.

---

## Phase 1. Pre-flight checks on the test server

Run these and record the results.

```bash
n8n --version                      # or check Settings > About in the n8n UI
hermes --version
hermes gateway status
gh --version                       # GitHub CLI, needed by Hermes
curl -sI https://<n8n-public-host>/healthz
```

Must be true before continuing:

- [ ] n8n is reachable **from the public internet over HTTPS** (GitHub Actions has to call its webhook).
      If n8n is only on a private network or `localhost`, stop and **ASK** how to expose it
      (reverse proxy with TLS, or a tunnel).
- [ ] n8n is a recent version. The Telegram node must offer the operation **"Send message and wait for
      response"**. If it does not, update n8n first.
- [ ] Hermes gateway is running and has scheduled jobs (cron) available. Check `hermes --help` for the
      exact command name.
- [ ] The server clock is in sync (`timedatectl`); the brief logic uses UTC.

**Note this is a test server.** If it goes down, the GitHub side keeps collecting and still creates the
WordPress draft; only approval and social posting stop. Fine for a trial; **ASK** before treating it as
permanent.

---

## Phase 2. Put the code on GitHub

On Ajit's Mac (or wherever the folder is copied):

```bash
cd ~/Developer/maritime-security-tracker
rm -rf .venv out .pytest_cache
git init -b main
git add .
git commit -m "Maritime security tracker: initial version"
gh repo create <OWNER>/maritime-security-tracker --public --source . --push
```

**ASK:** which GitHub account or organisation owns the repo (Ajit's personal account or `SpliceRun`).

Then in the repo on github.com:

1. Settings > Actions > General > Workflow permissions: **Read and write permissions**.
2. Settings > Pages > Build and deployment > Source: **GitHub Actions**.
3. Issues > Labels > New label: `verify`.
4. Settings > Secrets and variables > Actions:

| Name | Kind | Value | Who provides |
|---|---|---|---|
| `LLM_API_KEY` | secret | DeepSeek API key | **ASK** Ajit |
| `FIRMS_MAP_KEY` | secret | free key from https://firms.modaps.eosdis.nasa.gov/api/map_key/ | anyone, takes 1 minute |
| `WP_USER` | secret | WordPress bot user login (Phase 3) | Phase 3 |
| `WP_APP_PASSWORD` | secret | its Application Password | Phase 3 |
| `N8N_WEBHOOK_URL` | secret | production URL of the n8n webhook (Phase 4) | Phase 4 |
| `N8N_WEBHOOK_TOKEN` | secret | long random string: `openssl rand -hex 32` | generate |
| `WP_URL` | variable | `https://imariners.com` | |
| `PUBLISH_MODE` | variable | `draft` | keep `draft` for the first 2 to 4 weeks |
| `VERIFIERS` | variable | GitHub username Hermes posts as, if not the repo owner | Phase 5 |

Check:
- [ ] Actions tab > **Collect and process** > Run workflow. It finishes green in under 20 minutes.
- [ ] A commit "data: update ..." appears and `data/incidents.json` now has incidents.
- [ ] If any incident needed checking, issues labelled `verify` were opened.
- [ ] **Dashboard (GitHub Pages)** ran and the Pages URL shows the map.

If the run fails on DeepSeek, the log shows `LLM call failed`. Check the key and account balance.
The pipeline falls back to GitHub Models automatically, so a run can still succeed while DeepSeek is broken;
look for that warning in the log.

---

## Phase 3. WordPress (imariners.com)

**ASK** Ajit for an admin login, or have him do these four steps himself:

1. Posts > Categories > add **Maritime Security**, slug `maritime-security`.
2. Users > Add New > username `security-desk`, role **Author**.
3. Users > `security-desk` > Application Passwords > name `tracker` > copy the password
   into the GitHub secret `WP_APP_PASSWORD`, and the username into `WP_USER`.
4. If a security plugin (Wordfence, iThemes, etc.) blocks REST API logins, allow this user.

Rules for this site (from earlier decisions, do not break them):
- Do **not** add the brief to the homepage. It lives only in its category.
- No em dashes in any title, excerpt or content (the code already removes them).
- Do not edit pages with the Bricks builder as part of this work.

Check:
- [ ] Actions > **Daily brief** > Run workflow with **Preview** ticked > download the `brief` artifact.
      `brief.html` reads well and `brief-<date>.png` shows the two maps.
- [ ] Run **Daily brief** again **without** Preview. A **draft** post appears in WP admin under
      Maritime Security, with the featured image set.

---

## Phase 4. n8n on the test server

1. Workflows > Import from file > `n8n/maritime-brief-social.json` from the repo.
2. Create and attach credentials:

| Node | Credential | Notes |
|---|---|---|
| Brief from GitHub (Webhook) | **Header Auth**: name `X-Tracker-Token`, value = `N8N_WEBHOOK_TOKEN` | rejects anyone else calling the webhook |
| Ask me on Telegram, Tell me it's done, Tell me it was skipped | **Telegram API** (bot token from @BotFather) | **ASK** Ajit to create the bot and send it one message; then get his chat id from `https://api.telegram.org/bot<TOKEN>/getUpdates` and replace every `REPLACE_WITH_YOUR_TELEGRAM_CHAT_ID` |
| Publish on iMariners | **WordPress API** credential: `security-desk` + its Application Password | Author can publish its own posts |
| Post on X | **X OAuth2** | **ASK** Ajit for the X developer app. Confirm the plan allows posting via API |
| Post on LinkedIn | **LinkedIn OAuth2** | replace `REPLACE_WITH_YOUR_LINKEDIN_PERSON_ID`. Posting as the iMariners company page needs LinkedIn Community Management API approval: **ASK** whether to apply now |

3. The JSON was written by hand and has not been imported before. **Open every node** after import and
   check the fields are filled in as described. Fix anything n8n dropped. In particular:
   - Telegram "Ask me on Telegram": operation is *Send message and wait for response*, approval type
     *Approve and disapprove*, labels Publish / Skip, wait limit 6 hours.
   - "Social text": five fields (`link`, `title`, `excerpt`, `x_text`, `li_text`).
   - "Post on X" and "Post on LinkedIn" have *Continue on fail* on, so one failing network does not
     block the other.
4. Activate the workflow. Copy the **production** webhook URL into the GitHub secret `N8N_WEBHOOK_URL`.

Test with a fake payload before connecting GitHub (use a real draft post id from Phase 3):

```bash
curl -X POST "<production webhook URL>" \
  -H "Content-Type: application/json" \
  -H "X-Tracker-Token: <N8N_WEBHOOK_TOKEN>" \
  -d '{"post_id": <draft id>, "link": "https://imariners.com/?p=<draft id>",
       "status": "draft", "needs_approval": true, "wp_url": "https://imariners.com",
       "title": "TEST: Black Sea and Hormuz Shipping Attacks", "excerpt": "Test only.",
       "x_post": "Test post, please ignore", "linkedin_post": "Test post, please ignore",
       "counts": {"new": 0, "updated": 0, "corrections": 0}}'
```

Check:
- [ ] Ajit gets the Telegram message with Publish / Skip buttons.
- [ ] **Skip** sends the "Skipped" message and the post stays a draft.
- [ ] For the **Publish** test, temporarily disable the X and LinkedIn nodes (or use test accounts),
      then confirm the WordPress post becomes published and the "done" message arrives.
      Delete or unpublish the test post afterwards.
- [ ] Re-enable X and LinkedIn only when Ajit says the real accounts can go live (**ASK**).

---

## Phase 5. Hermes on the test server

1. Model: point Hermes at DeepSeek as an OpenAI-compatible provider
   (base URL `https://api.deepseek.com`, model `deepseek-chat`, the DeepSeek key).
   Use a Hermes profile for this job, e.g. `maritime`, so it does not change other SpliceRun profiles.
2. GitHub access: `gh auth login` on the server with an account that can comment on the repo's issues.
   - If it is the repo owner's account, nothing else is needed.
   - If it is a separate bot account, add its username to the repo variable `VERIFIERS`.
   - Use a fine-grained token limited to this one repo, with Issues: read and write. Nothing more.
3. Web access: Hermes needs browsing/search to check vessels and advisories.
4. Create a scheduled job every 3 hours using the task prompt in `docs/hermes.md` (replace `<OWNER>`).

Check:
- [ ] Pick one open `verify` issue and run the job once by hand.
- [ ] Hermes posts exactly one comment that starts with `/verdict ...` and contains at least one `source:` line.
- [ ] The **Apply verdict** workflow runs, the issue closes, and the incident's status in
      `data/incidents.json` changes.
- [ ] If the comment was ignored, the Actions log says "not owner or listed verifier": fix `VERIFIERS`.

---

## Phase 6. Trial run (2 to 4 weeks)

- Leave `PUBLISH_MODE=draft`. Every morning Ajit approves or skips on Telegram.
- Once a week, review:
  - false incidents that got through (tighten `config/keywords.yaml` or the prompt in `tracker/extract.py`)
  - attacks that were missed (add channels to `config/channels.yaml`, queries to `config/feeds.yaml`)
  - DeepSeek spend (expected 1 to 2 USD a month)
  - Telegram channels logging "returned no posts" (handle changed; find the new one)
- When the briefs need no edits for a week or two, set `PUBLISH_MODE=publish`. The approval step is then
  skipped and posting is automatic.

---

## Never do

- Never put keys or passwords in the repo, workflow files, or n8n workflow JSON. The repo is **public**,
  including Actions logs.
- Never publish an incident from satellite data alone, and never upgrade a "claimed" incident without a
  second, independent source. The code enforces this; do not bypass it.
- Never publish crew names or the live position of a vessel still in danger.
- Never run the n8n workflow against the live X or LinkedIn accounts during testing.
- Never change other SpliceRun projects, n8n workflows or Hermes profiles on the test server as part of this.

---

## Questions for Ajit (collect answers before Phase 2)

1. GitHub owner for the repo: personal account or the `SpliceRun` organisation?
2. Public n8n URL on the test server, and is it allowed to receive calls from GitHub?
3. DeepSeek API key: does one exist, and is billing set up?
4. Who creates the WordPress user and category (Ajit, or does the agent get admin access)?
5. X: which account, and is there a developer app with posting access?
6. LinkedIn: post from Ajit's profile for now, and apply for company page access?
7. Include the **Red Sea / Gulf of Aden** too? (Off by default; one switch in `config/regions.yaml`.)
8. Is the test server the long-term home, or should this move later?

---

## Report back

When finished, send Ajit one summary with:

- the GitHub repo URL and the Pages dashboard URL
- each phase: done, or blocked with the reason
- the test WordPress post id, and confirmation it was removed or unpublished
- any n8n node that needed fixing after import, and what was changed
- answers still missing from the questions list

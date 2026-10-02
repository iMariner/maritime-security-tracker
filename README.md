# Maritime Security Tracker

Tracks attacks on vessels in the **Black Sea** and the **Strait of Hormuz / Gulf / Gulf of Oman**,
from news, official advisories, public Telegram channels (both sides of the conflict, five languages)
and NASA satellite fire detections. Every morning it writes the **Maritime Security Brief**, publishes
it on imariners.com and shares it on X and LinkedIn.

Everything runs free on GitHub Actions (public repo). The only running cost is the DeepSeek API,
roughly 1 to 2 USD a month at this volume. Without AI credit the tracker still collects, but the run fails
and no incidents are extracted.

```
Every 30 min (GitHub Actions: collect.yml)
  Telegram (t.me/s) + RSS + Google News (en/uk/ru/tr/ro) + NASA FIRMS
  -> keyword pre-filter -> DeepSeek extracts incidents -> match/merge into data/incidents.json
  -> doubtful ones open a GitHub issue labelled "verify" -> Hermes (or you) answers /verdict

Daily 05:40 UTC (daily-brief.yml)
  last 24h incidents -> DeepSeek writes headline, overview, X and LinkedIn text
  -> map image -> WordPress post on imariners.com (draft or publish)
  -> n8n webhook -> Telegram approval on your phone -> publish + X + LinkedIn

On every data change (pages.yml)
  public map dashboard on GitHub Pages
```

Status labels used everywhere:

| Status | Meaning | Published? |
|---|---|---|
| confirmed | neutral authority (UKMTO, JMIC, coast guard), owner, flag state, or a verifier confirms | yes |
| reported | independent media, or both sides, or two unrelated outlets | yes |
| claimed | one side of the conflict only | yes, worded as a claim |
| signal | satellite fire at sea only | no, sent to verification |
| rejected | checked and false | no (a correction is printed if it was published earlier) |

## Setup (one time, about an hour)

Deploying on the SpliceRun test server (n8n + Hermes there): follow
[docs/DEPLOY-ON-TEST-SERVER.md](docs/DEPLOY-ON-TEST-SERVER.md), which is the step-by-step work order.
The sections below are the short version.

### 1. GitHub
1. Create a **public** repo named `maritime-security-tracker` and push this folder.
2. Settings > Actions > General > Workflow permissions: **Read and write**.
3. Settings > Pages > Source: **GitHub Actions**.
4. Issues > Labels: create a label named `verify`.
5. Add secrets and variables (Settings > Secrets and variables > Actions):

| Name | Type | Value |
|---|---|---|
| `LLM_API_KEY` | secret | DeepSeek API key (platform.deepseek.com) |
| `FIRMS_MAP_KEY` | secret | free key from firms.modaps.eosdis.nasa.gov/api/map_key |
| `WP_USER` | secret | login of the WordPress bot user |
| `WP_APP_PASSWORD` | secret | its Application Password |
| `N8N_WEBHOOK_URL` | secret | production URL of the n8n webhook node |
| `N8N_WEBHOOK_TOKEN` | secret | any long random string (same value in n8n Header Auth) |
| `WP_URL` | variable | `https://imariners.com` |
| `PUBLISH_MODE` | variable | `draft` for the first weeks (you approve on Telegram), later `publish` |
| `VERIFIERS` | variable | GitHub usernames allowed to post `/verdict`, comma separated (you are always allowed) |
| `LLM_BASE_URL`, `LLM_MODEL_FAST`, `LLM_MODEL_BRIEF` | variable | optional; defaults are DeepSeek / `deepseek-chat` |

Any OpenAI-compatible provider works: change only `LLM_BASE_URL`, the model names and the key.
(A GitHub Models fallback exists behind `LLM_FALLBACK=github`, but that service stopped answering in October 2026.)

### 2. imariners.com (WordPress)
1. Posts > Categories: create **Maritime Security** with slug `maritime-security`.
2. Users > Add New: a user such as `security-desk` with role **Author**.
3. Edit that user > Application Passwords: create one named "tracker" and copy it into `WP_APP_PASSWORD`.
4. If a security plugin blocks REST API logins, allow this user.
5. Posts use your normal single-post template. Add a little CSS for the incident table if you like:
   `.msb-incident th{text-align:left;width:30%}`

### 3. n8n (on a cloud server, not the ship laptop)
1. Import `n8n/maritime-brief-social.json`.
2. Credentials to attach:
   - **Brief from GitHub** webhook: Header Auth, name `X-Tracker-Token`, value = `N8N_WEBHOOK_TOKEN`
   - Telegram nodes: a bot from @BotFather; put your chat id in place of `REPLACE_WITH_YOUR_TELEGRAM_CHAT_ID`
   - **Publish on iMariners**: WordPress credential (an Editor or the bot user's app password)
   - **Post on X**: X OAuth2 credential (check your X API tier allows posting)
   - **Post on LinkedIn**: LinkedIn OAuth2; set your person id. Company page posting needs
     LinkedIn's Community Management API approval (apply early). LinkedIn tokens expire about
     every 60 days, so reconnect the credential when the "done" message shows a LinkedIn failure.
3. Open each node once to confirm the fields survived import, then activate the workflow and
   copy the production webhook URL into `N8N_WEBHOOK_URL`.

### 4. Hermes
See [docs/hermes.md](docs/hermes.md). Hermes works the `verify` issues; you can also answer
them yourself from the GitHub mobile app.

### 5. First run
Actions > **Collect and process** > Run workflow. Then Actions > **Daily brief** > Run workflow
with **Preview** ticked, and download the `brief` artifact to check the article and image.

## Local use

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m tracker.run_pipeline --dry-run   # collect + keyword filter only
.venv/bin/python -m tracker.brief --preview          # writes out/brief.html and out/brief-<date>.png
```

## Tuning

- `config/channels.yaml`: Telegram channels (add `side` and `kind` for each).
- `config/feeds.yaml`: RSS and Google News queries.
- `config/keywords.yaml`: pre-filter words. Too many AI calls: tighten it. Missed incidents: widen it.
- `config/regions.yaml`: regions on/off (Red Sea and Gulf of Aden are listed but off), naval vessels on/off,
  FIRMS sea and port areas.

## Things to know

- Everything in a public repo is public, including Actions logs. Keys live only in Secrets.
- GitHub can delay scheduled runs by 10 to 30 minutes. This is a daily brief, not a real-time alarm.
- UKMTO, JMIC, MARAD and the NATO Shipping Centre block automated access; their advisories are
  picked up through Google News and by Hermes during verification.
- Both sides publish claims that turn out false. The brief never upgrades a claim without a
  second, independent source.
- Satellite fire detections are only leads. Nothing is published from satellite data alone.

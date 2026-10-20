# Living maritime tracker

This is an additive view of the existing collection and verification system. The
article writer, n8n approvals, publication jobs and their credentials are unchanged.
No new API account, database or duplicated secret is required.

## Components

- `site/living.html`, `living.css`, `living.js`: animated standalone page.
- `site/living-wordpress.html`: HTML block for the iMariners page. Assets and feed
  come from the existing GitHub Pages deployment.
- `tracker/living.py`: public projection of existing incidents plus reviewed evidence.
- `data/living-evidence.json`: structured casualty facts, sourced updates and image
  attribution, separate from article data.
- `Apply living evidence`: trusted `/evidence` comments update the overlay and deploy
  the same Pages site. Corrections retain earlier values in an audit history.
- `docs/hermes/skills/maritime-living-evidence/SKILL.md`: instructions for the existing
  Hermes profile. Adding this file alone does not activate a scheduled job.

## Counting policy

The archive's first observed date is displayed, rather than implying that a
comprehensive historical backfill has taken place. The timeline sorts by attack
date descending; later information also appears in the recent-updates section.
Confirmed and reported records are distinguished from one-sided claims. Rejected,
merged, satellite-only and identifiable military records are excluded.

Death counts and nationalities require explicit structured confirmation and source
URLs. Existing free-text casualty statements are displayed as context, never parsed
into totals. Unknown does not mean zero. Nationality is never inferred from flag.

The legacy matcher may combine separate attacks on a vessel with the same IMO.
Until those historical records are audited, figures describe documented incident
records and must not be represented as an exhaustive total of actual attacks.

## Operation

The existing collectors and verdicts refresh the page through the existing Pages
action. Existing sourced `latest_news` updates are reused when their timestamps can
be linked to a source. Verified structured changes use the `/evidence` command
documented in the Hermes skill. Its action validates shape, not real-world truth.
Check both evidence and deployment runs before treating an update as live.

Images are optional and require an accurate source, credit, alt text and permission
to publish. Designed vessel illustrations fill missing images without implying
that they depict the actual attack.

## Check locally

Run `.venv/bin/python -m pytest -q`, build with
`python3 -m tracker.living --output out/living-incidents.json`, then serve a directory
containing the `site/living.*` assets and generated JSON through a local HTTP server.

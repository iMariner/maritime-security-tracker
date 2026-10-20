# Living maritime tracker

This is an additive view of the existing collection and verification system. The
article writer, n8n approvals, publication jobs and their credentials are unchanged.
No new API account, database or duplicated secret is required.

## Installed 20 October 2026

The standalone view is deployed at
https://imariner.github.io/maritime-security-tracker/living.html . WordPress page
16139, "Maritime Attack Tracker", is saved as a draft and verified in the existing
administrator preview at https://imariners.com/?page_id=16139&preview=true .
Its content is `site/living-mount-wordpress.html`: a native mount that loads the
latest shared markup, styling, renderer and data. Further design updates deploy
through Pages without repeatedly pasting the full WordPress block.

A separate Hermes job named `maritime-living-evidence` is scheduled every six hours
in the existing maritime profile. It reads the repository skill on each run, checks
at most three records using terminal and web tools, and keeps its results local.
Existing publication jobs and n8n were not edited. The first run was requested;
successful factual enrichment has not yet been established. The WordPress page
remains a draft while historic event matching and casualty evidence are audited.

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

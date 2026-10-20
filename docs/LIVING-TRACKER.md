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

Only explicit source-reviewed overlays are public. Old confirmed/reported/claimed
labels are research inputs, not automatic public approval. Every displayed vessel
must have a reviewed name, type, date, account and supporting links. Unreviewed
records stay in the original archive, outside this page and its totals.

The initial reviewed release contains eight named vessel/date records, not a full
historical attack total. Duplicate vessel/date records are withheld. The legacy
matcher can still combine repeat attacks, so historical completeness is not claimed.
Source date/timezone differences are recorded rather than replaced with invented
UTC event times. The displayed coverage begins with the earliest reviewed date.

Deaths and deceased nationalities require separate sourced counts. Missing crew
remain missing, never presumed dead. Safety of one nationality group does not
establish safety of the entire vessel. Incomplete zero-death coverage displays
Pending; positive partial totals are lower bounds. No nationality is inferred
from flag. See VERIFICATION-AUDIT-2026-10-20.md for checked sources and limitations.

## Operation

The existing collectors and Pages deployment continue to run. The public view
reads only reviewed overlay facts, sources and revision notes; raw pipeline
summaries, latest-news text and incidental timestamps cannot leak into it.
Hermes loads the dedicated evidence skill, reviews sources and proposes complete
verification objects through /evidence. The action validates structure, not truth.
Check both evidence and deployment runs before treating a change as live.

Images are optional and require an accurate source, credit, alt text and permission
to publish. Designed vessel illustrations fill missing images without implying
that they depict the actual attack.

## Check locally

Run `.venv/bin/python -m pytest -q`, build with
`python3 -m tracker.living --output out/living-incidents.json`, then serve a directory
containing the `site/living.*` assets and generated JSON through a local HTTP server.

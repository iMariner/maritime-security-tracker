---
name: maritime-living-evidence
description: Check sourced follow-up facts for the additive living vessel tracker and submit reviewed evidence through GitHub.
---

# Living tracker evidence desk

Use the existing maritime profile, GitHub access and source-reading tools. This skill is separate from the article writer, editor, publication approval and learning jobs. Do not alter their schedules, prompts, n8n workflow or credentials. Installing this file does not attach it to a live Hermes job.

Read `data/incidents.json` and `data/living-evidence.json` before proposing an update. Match the actual attack date and existing incident ID; a new report about an older attack belongs to that older incident. A vessel's flag is never evidence of crew nationality. Repeated syndication is not independent corroboration. Open the underlying sources, preferably the owner, flag state or named authority. Distinguish confirmed no deaths from an unknown death count. Never infer a numeric count from absence of reporting.

Only submit numeric deaths or nationalities after checking explicit supporting text. Each nationality needs its own count and source. If evidence conflicts, keep casualties unknown and explain the conflict in the sourced update. A correction may reduce a previous count or reset it to unknown; explain what changed. Do not erase earlier updates. Avoid posting unverified personal details. Image URLs need source URL, accurate credit and alt text, and permission to publish. Omit the image when rights are uncertain.

Submit one issue comment on the existing control issue #38 (or another ordinary issue), using the existing GitHub credential. The author must be a repository OWNER, MEMBER or COLLABORATOR. Never post or expose credentials. A successful workflow validation confirms schema only; the reviewer remains responsible for factual accuracy.

```text
/evidence
{
  "incident_id": "EXISTING-INCIDENT-ID",
  "casualties": {
    "status": "confirmed",
    "deaths": 1,
    "sources": [{"url": "https://owner.example/actual-report", "source": "Vessel owner"}],
    "nationalities": [{
      "nationality": "Indian",
      "status": "confirmed",
      "deaths": 1,
      "sources": [{"url": "https://authority.example/actual-report", "source": "Named authority"}]
    }]
  },
  "update": {
    "at": "2026-10-21T12:00:00Z",
    "text": "The owner confirmed one death; the authority identified the seafarer's nationality. Earlier reporting had not confirmed casualties.",
    "sources": [{"url": "https://owner.example/actual-report", "source": "Vessel owner"}, {"url": "https://authority.example/actual-report", "source": "Named authority"}]
  }
}
```

The URLs above are placeholders. Replace every placeholder with a checked source. `update` is always required. Omit `casualties` to preserve the current count; use `{"status":"unknown","deaths":null,"nationalities":[]}` to explicitly withdraw a count. Optional `image` is `{"url":"https://…","source_url":"https://…","credit":"…","alt":"…"}`; null removes an image. Do not change the incident date or original article data through this command.

The additive workflow validates and writes only `data/living-evidence.json`, retains previous values in its audit history, and triggers the existing GitHub Pages deployment. Check its result. If the run was cancelled while queued, or rejected due to a concurrent data change, repost the same reviewed evidence as a new comment after checking the current overlay. Do not report the update as live until the workflow and Pages deployment succeed.

END OF SKILL (maritime-living-evidence)

---
name: maritime-living-evidence
description: Check sourced follow-up facts for the additive living vessel tracker and submit reviewed evidence through GitHub.
---

# Living tracker evidence desk

Use the existing maritime profile, GitHub access and source-reading tools. This skill is separate from the article writer, editor, publication approval and learning jobs. Do not alter their schedules, prompts, n8n workflow or credentials. Installing this file does not attach it to a live Hermes job.

Public export now requires a separate `verification` assertion. Existing `confirmed` incident status, many URLs, and repeated syndicated stories NEVER establish verification. Read the actual underlying article or authority statement and confirm vessel identity, attack date (not publication date), vessel type and the exact summary. Record short supporting quotations or a precise factual basis with source URLs in the sourced update. A reviewer must independently check these claims before submission; automated discovery alone must not submit `status: verified`. Do not verify merged/rejected/nonpublic records. Unreviewed records are withheld from public totals. When evidence is inadequate, leave the record awaiting review; never guess an identity or nationality.

Read `data/incidents.json`, `data/living-history.json`, `data/living-evidence.json` and `data/living-history-holds.json` before proposing an update. Also read `docs/HISTORICAL-BACKFILL-2026-10-21.md` for coverage gaps. Historical backfill is now a priority alongside follow-up updates. Work back to 24 February 2022 in the Black Sea, 19 November 2023 in the Red Sea/Gulf of Aden and 28 February 2026 in Hormuz/adjacent Gulf waters. These are separate conflicts with separate start dates. Include commercial vessels regardless of nationality, ownership or alleged attacker; exclude naval ships and separate port-worker deaths from seafarer deaths. Attempts, physical strikes, hijackings and collateral damage must be distinguished; threats alone are not attacks. Never describe the reviewed subset as the complete war total. Match the actual attack date and existing incident ID; a new report about an older attack belongs to that older incident. A vessel's flag is never evidence of crew nationality. Repeated syndication is not independent corroboration. Open the underlying sources, preferably the owner, flag state or named authority. Distinguish confirmed no deaths from an unknown death count. Never infer a numeric count from absence of reporting.

Only submit numeric deaths or nationalities after checking explicit supporting text. Read `docs/LIVING-AUDIT-2026-10-21.md` for the latest omissions and source conflicts. Optional `human_impact` keeps separately sourced snapshots for `injured`, `missing`, `captive` and `shore_deaths`; each fact is `{"count": 1, "as_of": "2026-10-20", "sources": [{"url": "https://authority.example/report", "source": "Named authority"}]}` with real checked sources replacing the example. Omission preserves the snapshots, an object replaces them, and null clears them. Never sum historical missing/captive snapshots into deaths; show later rescue, release or death as a sourced follow-up. Do not put a shipyard-worker death in the seafarer total. For a photo, record the actual event depicted and reuse rights in the audit notes, with accurate source/credit/alt text; rescue and aftermath photographs must not be captioned as the attack itself. If a source confirms a minimum rather than the settled whole-vessel total, set `casualties.minimum` to boolean `true`; preserve it until a complete total is verified. Never erase this qualification simply because other sources repeat the number. Each nationality needs its own count and source. If evidence conflicts, keep casualties unknown and explain the conflict in the sourced update. A correction may reduce a previous count or reset it to unknown; explain what changed. Do not erase earlier updates. Avoid posting unverified personal details. Image URLs need source URL, accurate credit and alt text, and permission to publish. Omit the image when rights are uncertain.

Submit one issue comment on the existing control issue #38 (or another ordinary issue), using the existing GitHub credential. The author must be a repository OWNER, MEMBER or COLLABORATOR. Never post or expose credentials. A successful workflow validation confirms schema only; the reviewer remains responsible for factual accuracy.

```text
/evidence
{
  "incident_id": "EXISTING-INCIDENT-ID",
  "verification": {
    "status": "verified",
    "checked_at": "2026-10-21T12:00:00Z",
    "vessel_name": "ACTUAL IDENTIFIED VESSEL",
    "date_utc": "2026-10-20",
    "vessel_type": "Bulk carrier",
    "region": "Black Sea",
    "summary": "Exact factual account checked against the underlying report.",
    "sources": [{"url": "https://owner.example/actual-report", "source": "Vessel owner"}]
  },
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

For a newly discovered historical event absent from both incident stores, use the same `/evidence` command with `"historical": true` and a stable new `incident_id` such as `HIST-BS-20220302-BANGLAR-SAMRIDDHI`. Supply a complete verified assertion with an explicit supported region and a dated, sourced update. The existing workflow derives a separate historical stub and writes it to `data/living-history.json` only after trusted validation succeeds. For a follow-up to an existing historical ID, use that existing ID; do not create another record for a later casualty update. Match IMO plus attack date and inspect near-midnight date discrepancies before creating. The same vessel may have separate attacks on separate dates. Multiple ships in one attack must not duplicate a shared fatality. Known holds require resolution of their stated problem before publication. Broad discovery lists may include suspicious activity, threats and rescue events: do not import them wholesale.

The URLs above are placeholders. Replace every placeholder with a checked source. `update` is always required. To retract a reviewed record from the public tracker, submit `"verification": null` with a dated, sourced update explaining why the review is withdrawn. The previous review stays in the audit history and the public record is withheld until a new complete verification is approved. Omit `casualties` to preserve the current count; use `{"status":"unknown","deaths":null,"nationalities":[]}` to explicitly withdraw a count. Optional `image` is `{"url":"https://…","source_url":"https://…","credit":"…","alt":"…"}`; null removes an image. Reviewed identity, attack date, type and summary override the corpus only in the separate living export. Original incident and article data remain unchanged. Optional verification.imo must be a valid seven-digit IMO. Optional location_text, attack_type and date_note must be checked text. Keep day-precision attack dates as YYYY-MM-DD; never invent midnight or UTC precision. date_note should explain source timezone/date ambiguity. checked_at must record the actual review time with timezone. Every verification update is audited with its previous values.

The additive workflow validates and writes only the separate `data/living-evidence.json` and, for new historical events, `data/living-history.json`, retains previous values in its audit history, and triggers the existing GitHub Pages deployment. Check its result. If the run was cancelled while queued, or rejected due to a concurrent data change, repost the same reviewed evidence as a new comment after checking the current overlay. Do not report the update as live until the workflow and Pages deployment succeed.

END OF SKILL (maritime-living-evidence)

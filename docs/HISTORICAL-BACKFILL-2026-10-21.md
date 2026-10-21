# Historical living-record backfill — 21 October 2026

This is a reviewed historical expansion, **not a complete count of every wartime attack**. The page must retain its backfill notice until source reconciliation and coverage checks are finished. The original article corpus, article approvals, publishing jobs, n8n configuration and credentials were not changed.

## Published batch

The separate historical store adds 218 reviewed vessel/date records to the eight existing public reviews: **226 records, 222 distinct vessel identities** (IMO where available, otherwise normalized name), with **at least 37 confirmed seafarer deaths**. Sourced nationalities currently account for 22 of those documented deaths: Indian 6, Filipino 6, Syrian 4, Thai 3, Bangladeshi 1, Ukrainian 1, Vietnamese 1. These nationality figures are incomplete; nationality is never inferred from flag.

| Region | Reviewed records | Earliest reviewed date |
| --- | ---: | --- |
| Black Sea / Sea of Azov | 38 | 24 February 2022 |
| Red Sea / Gulf of Aden | 72 | 19 November 2023 |
| Hormuz and adjacent Gulf waters | 116 | 1 March 2026 |

The intended historical baselines are the start of each separate conflict: 24 February 2022, 19 November 2023, and 28 February 2026 respectively. The earliest documented record is not a claim that no attack occurred before it. The current corpus includes physical strikes, attempted attacks, seizures and collateral damage; records distinguish these where the source establishes the event type. Multiple weapons do not become multiple vessel records. Separate dated attacks on the same vessel remain separate incidents, but the distinct-vessel total counts that identity once.

## Principal sources and review

- [IMO current Middle East confirmed incident register](https://www.imo.org/en/mediacentre/hottopics/pages/middle-east-highlighted-incidents.aspx): all 116 rows as at 20 October, read on 21 October. Four existing richer reviews were retained instead of duplicated. GFS GISELLE has a one-day local/IMO reporting difference and is counted once. The official register's 24 seafarer deaths reconcile with the included rows; its separate STENA IMPERATIVE shipyard-worker death is excluded.
- [IMO Red Sea register, 12 September 2024](https://wwwcdn.imo.org/localresources/en/MediaCentre/Documents/Red%20Sea%20Incidents%20Report%20for%20Member%20States%2012%2009%202024.pdf) and the [8 May annex](https://wwwcdn.imo.org/localresources/en/MediaCentre/HotTopics/Documents/Red%20Sea/Red%20Sea%20Incidents%20-%208%20May%202024.pdf): read named rows, types and outcomes. MSC ALANYA is explicitly not attacked and was excluded. Additional cited October 2024 and 2025 events were checked separately. The official aggregate and the broader JMIC list use different inclusion criteria; their headline totals were not added to this record tally.
- [Ukraine submission A34/23/2, hosted by the Council of the EU](https://data.consilium.europa.eu/doc/document/WK-15310-2025-INIT/en/pdf): 23 exact-date named physical-damage events accepted with attribution, rather than treating a party's submission as independent corroboration. Several claimed deaths in this document concern shore workers and are excluded from seafarer totals. Early 2022/2023 and Russian commercial-vessel attacks were checked separately against linked government, owner, Reuters/AP and maritime-industry reports.
- Specific Hormuz classifications were checked against INTERTANKO, the Swedish Club public insured-vessel register, ClassNK, operator fleets, JMIC and registry pages, with record-level links. Ship names were not used to infer type. EVER VICT is a tanker despite its name; HMM NAMU is general cargo. CAMEROON PROSPERITY's printed IMO has eight digits and was omitted rather than guessed; its narrow type remains under review.
- Each published entry retains its supporting URLs and a review timestamp in `data/living-evidence.json`. Historical stubs in `data/living-history.json` are separate from the article ingestion store and pass through the same export gate.

## Casualty safeguards

- Missing PETRO DOLPHIN, EL GAIA and MINOAN PIONEER personnel are not counted as dead.
- BADR is the damaged barge in the VOLANS/BADR joint tow operation. One death is attributed to the operation once; the source does not establish aboard which craft the person died. VOLANS's IMO and tug classification were not assigned to BADR.
- ETERNITY C has a confirmed minimum of three Filipino deaths; `casualties.minimum: true` preserves that qualification. It is not treated as a complete vessel-wide assessment. TUTOR's missing/deceased conflict is unresolved and excluded from death totals.
- TRUE CONFIDENCE: three deaths, two Filipino and one Vietnamese. MINERVAGRACHT: one Filipino death confirmed after the attack; it is attached only to the damaging 29 September event, not also the 23 September attempt.
- BANGLAR SAMRIDDHI: one Bangladeshi engineer. MJ PINAR: four Syrian crew. KMAX RULER: one Ukrainian maritime pilot. Pilot inclusion is explicit; shore workers are outside the seafarer tally.
- Indian nationality is separately sourced from the 27 March parliamentary annex for SKYLIGHT, MKD VYOM and SAFESEA VISHNU, and the PIB briefing for SETTEBELLO. SKYLIGHT's second IMO-confirmed death has no nationality assigned by inference. The SAFESEA VISHNU and SETTEBELLO source-date differences are visible in date notes and are not additional events.

## Remaining gaps

`data/living-history-holds.json` records seven candidates deliberately withheld for unresolved dates, scope, probable mine/no damage, floating-dock classification, or berth-only damage. Further work remains in 2022–2023 Black Sea coverage, late-2024/2025 Red Sea incidents and recent Black Sea events. JMIC's broader discovery list contains suspicious activity, threats, piracy and SOLAS events as well as attacks, so it must not be bulk-imported as an attack count.

Use the existing Hermes living-evidence desk to expand and reconcile this history. It can now create a separately reviewed historical record with `/evidence`, `historical: true`, a stable `HIST-*` ID, complete verification and a dated sourced update. Existing historical IDs accept follow-up evidence using the same command. The trusted workflow writes the historical stub and overlay, then deploys through the existing Pages job. The article pipeline is not involved.

## Validation

Python tests cover historical export/reconciliation, trusted historical creation, rejected-ID precedence, replay, minimum casualty counts and source validation. Browser checks cover the expanded totals, historical year filter, vessel search, region filters, visible content with motion enabled and narrow-screen control layout. Build and deploy results are checked separately before reporting the batch live.

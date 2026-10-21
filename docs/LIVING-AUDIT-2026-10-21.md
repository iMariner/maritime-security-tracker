# Living record omission audit — 21 October 2026

## What was missing

The first historical batch had 226 records but **zero sourced photographs**, only one revision-history entry, and no structured injured/missing/captive snapshots. Its header total combined attacks, attempts, near misses and a hijacking, while 155 records had no precise event category. Tanker subtypes were scattered across many chips rather than a useful broad-category summary. Only 22 of the 37 documented deaths had sourced nationality.

The audit found no exact IMO/date or normalized name/date duplicates. The UI identity fallback was weaker than the export: punctuation variants and a later-known IMO could become different identities. It now normalizes names and resolves an absent IMO only when the same normalized name maps unambiguously to one known IMO. This is not fuzzy identity guessing; unresolved aliases stay in the review backlog.

## Corrections applied

- Added nine individually checked incidents: **TIHAMAH, SCARLET RAY, LADONNA, WAEL K, MATILDA, DELTA HARMONY, ABLE, ALFA WATAN and AYA**. Date conflicts are visible, not additional incidents. The new public dataset contains **235 records, 231 distinct vessel identities and at least 40 documented seafarer deaths**.
- Added nationality evidence for SIDR (two Filipino), the September HERCULES STAR event (one Filipino; second nationality still unresolved), and GFS GALAXY (one Indian). LADONNA adds one Syrian death and TIHAMAH adds a confirmed minimum of two Pakistani deaths. Nationality is now sourced for **29 of the 40 documented deaths**, across eight nationalities. Eleven documented deaths still lack sourced nationality.
- Restored separately sourced injury/missing snapshots from the IMO register. Shore deaths remain separate. No missing person is automatically converted to a death, and historical snapshots are not aggregated as a current missing-person total.
- Added GALAXY LEADER's later outcome: all 25 crew released on 22 January 2025. A dated zero-captive snapshot and a sourced revision replace the misleading impression of continuing captivity.
- Added a credited public-domain documentary photograph to TUTOR (rescue assistance, 15 June 2024), labelled as rescue rather than the moment of attack. Added a credited RUBYMAR sinking-photo source in its evidence history; the external asset returned HTTP403, so its embed is withheld. Source and credit remain visible; embedded images retain their aspect/context and have an unavailable-image fallback.
- Added an incident-category filter and explicit category counts. `Other / unclassified` is retained where the source review does not establish the mechanism. It is not silently relabelled as a successful strike.
- Added broad vessel-type groups with expandable subtypes; dropdown filtering still uses the detailed classification.
- CAMEROON PROSPERITY's malformed eight-digit IMO was reconciled with the separately named US Coast Guard registry entry: IMO 9315159, tanker. It was not corrected merely by deleting a digit.

## Important source reconciliations

### TIHAMAH — 11 August 2026

[IMO confirms fatalities](https://www.imo.org/en/mediacentre/pressbriefings/pages/statement-on-deadly-ship-attack-in-the-red-sea.aspx), but gives no numeric tally. [SABA's 14 August account](https://www.sabanew.net/story/en/150829) of Pakistan's UN statement reports three Pakistani and one Indonesian deaths. However, [Indonesian government reporting of the Foreign Ministry briefing on 13 August](https://tribratanews.jabar.polri.go.id/indonesia-kecam-keras-serangan-di-selat-bab-al-mandeb-tiga-abk-wni-di-kapal-mv-tihamah-dua-selamat-satu-masih-hilang/) identifies two injured Indonesian survivors and one missing Indonesian. [Radio Pakistan's 20 August body text](https://radio.gov.pk/20-08-2026/dpm-condemns-killing-of-3-pakistanis-in-houthis-attack-on-ship-in-red-sea) quotes the Deputy Prime Minister: six Pakistani injured returned and two bodies repatriated; its headline still says three killed. This body detail supports two Pakistani deaths as a conservative minimum. The contradictory additional deaths remain unresolved, not silently discarded or counted. Eight injured derives from the two consular accounts (six Pakistani + two Indonesian). One missing Indonesian remains a dated 13 August snapshot, not a claim that the person's status was freshly confirmed in October. Two Yemeni rescuers described in early reporting are not merchant-crew deaths.

### Black Sea gaps

The [USPA presentation of 23 April 2026](https://www.danubecommission.org/uploads/doc/2026/20260423_EM_PORTS/Vyacheslav_Kharkavenko_USPA_Seaports_of_Ukraine_Operating_in_the_war_time.pdf) reports a much wider damage picture (169 civilian vessels damaged/partially destroyed in its scope), with many names absent from the initial reviewed store. That aggregate has a different scope and is **not added to our individual-record total**. Thirty newly identified dated names/events are saved in `data/living-history-holds.json` for classification/identity reconciliation. NATAN/NATHAN may be spelling variants of one vessel; no two-vessel count is asserted.

INGULSKY is held for cause reconciliation: the dedicated source account says an unidentified explosive device and three crew deaths, while the overview groups it under attacks. Its infographic says eight injured, but the detailed account says four injured among eight rescued. Publishing a guessed injury figure or a definite deliberate-attack attribution would be wrong.

AYA is one missile-damage event: the historical inventory dates it 11 September 2024, while the Ukrainian UN letter and initial maritime report say 12 September. Both dates are explained in its record. Initial absence of reported casualties does not establish a final zero-death count.

### TUTOR

A dated Navy account lists one missing mariner. Later Philippine reporting declined to certify death, while other reports described a death. The audit does not add a numeric death or nationality-of-deceased by inference. Its rescue imagery and missing snapshot do not resolve the casualty conflict.

## Remaining work

Coverage is still incomplete, especially late-2024/2025 Red Sea attacks and Black Sea civilian/support craft. Some source claims are not independent named-vessel confirmation. Date intervals, possible mines, disputed aliases, and alleged attacks denied by managers remain outside public counts until reconciled. Most historical records still lack licensed documentary imagery and complete human-impact assessments. Their absence is a review gap, not zero harm.

The separate evidence workflow now accepts `human_impact` snapshots with integer counts, exact as-of dates and named sources; it audits replacements and rejects invalid claims. News publication, n8n and its credentials are unchanged.

## Verification limits

144 Python tests pass. A network-free renderer unit check verifies headline totals, normalized vessel identity, nationality coverage, attempted-attack and year filters, dated human-impact output and documentary credit markup. Browser security policy blocked local preview acquisition, so this audit does not claim a fresh visual layout check. The Tutor image asset returned HTTP200; the blocked Rubymar asset was not embedded.

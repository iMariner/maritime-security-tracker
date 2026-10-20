# Live verification audit — 20 October 2026

This is a bounded audit of six named records, not approval of the full imported feed. No original incident/news data was changed. Proposed overlays are in `out/verification-proposals.json`; a reviewer must approve them before applying. Dates below describe the attack, not the date a story was ingested. All source pages were actually opened; exceptions are explicitly identified.

## Supported records and important corrections

- **JIF BARRACUDA, 18 October, IMO 9345506:** [IMO’s actual table](https://www.imo.org/en/mediacentre/hottopics/pages/middle-east-highlighted-incidents.aspx) names the ship northeast of Khor Fakkan, damaged, one seafarer injured. [Maritime Executive](https://maritime-executive.com/article/tug-attacked-near-strait-of-hormuz) identifies a tug, two projectiles and continued passage. The feed’s attribution to an unnamed tanker/mine claim should not attach to this tug. No fatality value is explicitly established by these sources.
- **GFS PRIDE, 13 October:** [Singapore MPA’s primary release](https://www.mpa.gov.sg/media-centre/details/two-singapore-registered-vessels-struck-in-strait-of-hormuz) calls it a Singapore-registered container vessel, attacked on 13 October **Singapore Time**, subsequently sunk; all 21 evacuated, no reported injuries. [WK Webster’s casualty report](https://wkwebster.com/casualties/772/gfs-pride) agrees and prints IMO 9349045. Do not fabricate UTC midnight. MPA states no Singaporeans aboard, which does not establish other crew nationalities. Its date for GFS GISELLE is 14 October Singapore Time versus IMO’s 13 October: time zone/day boundaries need preserving.
- **CHELSEA 3, 13 October:** [Bulgarian Transport Ministry’s primary operational bulletin](https://www.mtc.government.bg/bg/category/1/tekhnicheska-informaciya-za-zasegnatite-i-okazalite-sdeystvie-prez-poslednite-24-chasa-plavatelni-sredstva-v-morskite-prostranstva-na-republika-blgariya) reports the attack at 01:15, 17 nautical miles east of Byala, Malta flag, all 15 crew rescued. [BTA’s investigation report](https://www.bta.bg/en/news/1226692-military-prosecution-opens-investigation-into-attack-on-chelsea-3-in-black-sea) identifies general cargo and 13 October; its detailed indexed result was readable but direct opening returned 429. Rescue does not mean no injuries. AP’s indexed [13 October dispatch](https://apnews.com/article/7dfef251fb7d47a717f0d600873dbf5b) reports five minor injuries and seven Ukrainian/eight Azerbaijani crew; its direct page was inaccessible, so retain this access limitation.
- **YARA J, 14 October:** [HabarizaComores’ reproduced ANAM statement](https://www.habarizacomores.com/2026/10/attaque-dun-petrolier-battant-pavillon.html) identifies tanker IMO 9221803, drone attack on 14 October, Sulina, and all 17 crew safe. This is a reproduction of an authority statement, not a directly located ANAM-hosted original. Flag is not crew nationality. Do not conflate its safe crew with Wine Trader casualties.
- **WINE TRADER, 15 October:** [Romanian Naval Authority’s initial PDF](https://portal.rna.ro/wp-content/uploads/2026/10/Comunicat-de-presa-15.10.2026-Incident-nava-Wine-Trader.pdf) reports fire at approximately 07:00, 13 nautical miles southeast of Sulina, twelve aboard, initially four safe/eight missing. [ShipFinder’s later report](https://www.shipfinder.com/maritime-news/maritime-security/chemical-tanker-fire-wine-trader-sulina) identifies chemical tanker, five rescued/seven missing in its detailed indexed result; direct opening was inaccessible. The feed’s general-cargo classification is incorrect. [Türkiye Today on 20 October](https://www.turkiyetoday.com/world/russian-black-sea-strikes-deepen-perfect-storm-for-food-supplies-eu-3230696) quotes manager Salvadore Adorno: seven still missing, six Beninese and one Russian, search ended. It links [Maritime.bg’s original interview](https://www.maritime.bg/156457/), which returned 429. **Missing is not confirmed dead.** The nationalities may be displayed as missing-person reporting with attribution, never included in deaths by nationality.

## Additional checks

The live IMO table explicitly names **ST3, IMO 9220964, 16 October, 68 NM from Al Jubail**, damaged/no pollution. This provides a stronger exact named incident than a generic index or Google RSS URL. Its precise location should not be overwritten with a news headline’s broad Hormuz wording. This table alone does not prove vessel type, whole-crew safety, nationality, attacker or projectile. ST3 is therefore not one of the six full proposals.

## Consequences for public totals

An old `confirmed` status is not field-level validation. Name, type, attack date, fatalities and nationality each require support. Count only audited incidents in audited totals; disclose that coverage remains partial. All-crew-safe reports can establish a dated zero fatality assessment, but a blank IMO casualty cell cannot. Verified missing nationalities must stay separate from deceased nationalities. Repeated syndicated copies must not count as independent sources. Do not describe inaccessible originals as read.

## Red Sea follow-up: CUL KLANG

Both full articles opened: [Maritime Executive, 7 October](https://maritime-executive.com/article/shots-fired-at-chinese-containership-in-the-red-sea) and [SAFETY4SEA, published 9 October](https://safety4sea.com/armed-small-boat-opens-fire-on-containership-in-southern-red-sea/). They give attack date **7 October**, north of Bab el-Mandeb, containership identified by security consultants as CUL Klang, crew uninjured and northbound voyage continued. The feed’s separate 8 October language should not create another incident. Sources quote MSCIO; the underlying official advisory was not independently opened. Keep public incident status reported. No verified attacker, crew count or crew nationality list; AIS China-owned/Chinese-crew wording is self-broadcast, not independent nationality evidence. Sixth proposed overlay added for parent review.


## Approved public subset

The parent reviewed and applied six proposals plus the following two source-checked
records to `data/living-evidence.json`, with the actual review timestamp. This
supersedes the preliminary proposal-only status above; the rest of the imported
archive remains unreviewed and is excluded from the public page.

- **ST3, 16 October:** the opened IMO table supports name, IMO and 68 NM from Al
  Jubail. The opened [NDTV/ANI report quoting India's shipping minister](https://www.ndtv.com/india-news/24-indian-seafarers-safe-after-tankers-attacked-in-strait-of-hormuz-romania-12197556)
  supplies crude oil tanker, projectile strike and safety of 15 Indian nationals.
  The reviewed record retains the IMO location and describes the discrepancy with
  the broader Hormuz reporting. Safety of those nationals is not a whole-vessel
  zero-death claim.
- **GFS GISELLE:** the opened Singapore MPA release supplies container type,
  projectile strike, hull damage, safe arrival, all 22 safe and no reported injuries.
  MPA's 14 October Singapore Time differs from the IMO table's 13 October; the
  source date note preserves both. The public record uses the flag authority's day.

Zero-death assessments for GFS PRIDE and GFS GISELLE are sourced to the flag
state's all-crew-safe account. Other casualty totals remain unestablished in this
reviewed subset. Wine Trader's missing nationalities remain attributed reporting
in its account and do not enter deceased-nationality totals.

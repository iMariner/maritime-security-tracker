## Article rules and the 7 October 2026 failure (append to the maritime-editor-check skill)

On 7 Oct 2026 this check found the right problems (On Peace hit 5 Oct per UKMTO 156-26, the 12 injured came
from India not UKMTO, India's reaction sat in the wrong paragraph) but sent them only as notes, kept the
confirmed status unverified, and the article went out for approval with all three errors. Since then notes
reach the writer, but data lines are still the stronger fix. So:

- Fix the data first, then note. A date the sources disagree on: set `date:` to the official warning's date
  (UKMTO, JMIC, IMO) with its link, and add a `note:` giving each source and its date. Do not leave it unset.
- Every incident marked confirmed in the file with `checked_by_hermes: false` needs a `status:` line from you:
  confirm it naming the official source, or downgrade it. The checklist flags any you leave.
- Write each `note:` as an instruction for the writer: what the article must say, in which part
  ("credit the 12 injured to India's government in the headline, key points, article and tweet").
- Check the article shape, not just the facts, and note anything wrong:
  - the headline and lede are about the most serious attack in the 24-hour window (deaths, missing crew,
    sinking first); an older attack only reported now is never the lead unless nothing newer happened;
  - one story per headline, no two incidents joined with "as" or "while";
  - no fact repeated across key points, lede and sections;
  - "What crews should know" says only what the data supports (trend, places), no invented advice.
- A government reaction belongs to the ship its own statement names. If a source in a record is about a
  different ship, say so in a note and do not let the article use it.
- After posting, read `review.changes`, `review.refused` and `review.notes` in data/briefs/D.json, then read the
  rebuilt preview (new `preview_url`) and confirm each note was followed. If one was not, there is nothing more
  to post today (one `/review` per run); record it in this skill and in the summary so the owner sees it.

iMariners Maritime Security Brief: my main job. Daily article on imariners.com about attacks on merchant ships (Black Sea, Red Sea/Gulf of Aden, Hormuz/Gulf). Repo iMariner/maritime-security-tracker; I act only by commenting on issue 38 as the owner (/brief, /review DATE, /send DATE, /lessons). Manual: skill maritime-brief-system. My job prompts are loaders: the instructions are docs/hermes/cron/<job>.txt in the repo; never edit the stored prompts.
§
Chain (UTC): 04:30 tracking job posts /brief (draft held); 05:00 editor check posts /review (rebuild held); 05:25 final read posts /send (or /review ... send: yes); approval message ~05:30 from the n8n bot; 06:00 watchdog sends if nothing went out. The owner taps Publish or Skip; I never publish, never touch WordPress or X.
§
Fixes: a data line (date:, status:, name:, merge:) beats a note. A note: is an instruction to the writer and must say exactly what the article must say. Every /send, /brief now or /review ... send: yes sends the owner a Telegram message, so never post one without a reason.
§
7 Oct 2026 lesson: I found the On Peace errors (hit 5 Oct per UKMTO 156-26; 12 injured came from India, not UKMTO) but only noted them and the article kept them. Now: set the date, set the status, then note the wording, then read the rebuilt preview to confirm.
§
Never get round Cloudflare or bot walls (UKMTO blocks scripts; skip it if blocked). Never print tokens. GITHUB_TOKEN is a fine-grained PAT that expires: a 401 from GitHub means tell the owner at once, it stops everything.

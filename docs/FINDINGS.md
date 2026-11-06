# Findings — study of the input pack

Show: *I Married a Broken Soldier. He was a Duke* — 50 episodes, one `.txt` screenplay per episode.

## Size and shape
| Metric | Value |
|---|---|
| Episodes | 50 |
| Episode length | 70.5 s – 200.8 s (mean 123 s, ~2 min) |
| Total runtime | ~103 minutes |
| Scenes per episode | 1 – 5 (mean 2) |
| Timed blocks | 1,754 CAMERA · 1,487 DIALOGUE · 372 ACTION · 114 SOUND FX |
| Raw text | ~530k chars ≈ 132k tokens |
| Without CAMERA blocks | ~173k chars ≈ 43k tokens |

## Format
- Header per episode: `EPISODE NUMBER`, `EPISODE LOGLINE`, `CONTINUITY NOTES`.
- Every block has `Start: (MM:SS.ss) | End: (MM:SS.ss)`. No block has end < start.
- Dialogue blocks carry an **emotion tag**: `**JULIANA (Cold, Resolute):**`. Most common tags: Cold, Resolute, Desperate, Whispering, Defiant, Mocking, Shouting, Screaming, Furious, Cruel, Venomous.
- Timestamps restart at 00:00 every episode.

## Quirks a parser must handle
1. **Inconsistent casing**: Episode 6 uses `SCENE START:` / `SCENE END:` instead of `Scene start:` / `Scene end:`. A case-sensitive parser silently drops it.
2. **Character name drift**: the same person appears under different names — `JULIANA` / `LADY JULIANA`; `GERALD` / `THE FORMER GROOM`; `CLARISSA` / `LADY CLARISSA` / `LADY IN GOLD GOWN`; Alexander as `MYSTERIOUS BEARDED MAN` / `THE BEARDED STRANGER` before his name is revealed.
3. **Place name drift**: Ashbury / Ashbourne / Ashburn / Ashburton.
4. Dialogue lines sometimes overlap (10 cases); CAMERA and ACTION blocks overlap dialogue all the time (they are parallel tracks, not a sequence).

## Story-structure findings (these drive the design)
1. **Most episodes end on a cliffhanger, but not all.** Ep 7, 10 and 19 end on warm, resolved beats (smile, tender look, embrace). In 14/50 episodes the last spoken line is followed by 5–8.5 s of CAMERA/SOUND FX, and often *that* is the real cliffhanger (Ep 23: the door latch turning; Ep 35: a horrified close-up plus an orchestral swell).
   → A cliffhanger can be any block type, including CAMERA and SOUND FX, and "episode ending" ≠ "cliffhanger"; it must be judged.
2. **No recaps**: episodes do not replay the previous ending; they continue straight on.
3. **Keyword rules don't work for hooks.** A keyword count (slap/kiss/blood/duke/…) gives Episode 1 a score of **0**, yet the altar abandonment is one of the strongest hooks in the show. Judging a hook needs language understanding → an LLM is needed for judgement.
4. **Dialogue is dense**: median gap between lines 0.6 s, 90th percentile 3.3 s. Clean cut points (no one mid-sentence) exist but must be chosen carefully.
5. **The title is the promise.** "He was a Duke": the reveal happens across Ep 39–43 (regalia, cathedral explosion, guards salute the true Duke). Because the title already gives it away, these scenes are not spoilers; they are the payoff the ads sell.
6. **Sound tails can cross scene boundaries**: E22-B023 (SOUND FX) ends 0.3 s after its scene ends. Cut points must allow this.

## Story arc (for judging "makes sense on its own")
- Ep 1–5: jilted at the altar for her sister, disowned, marries a scarred stranger.
- Ep 6–18: cottage life; enemies frame Alexander, briar ordeal, thugs, arson.
- Ep 19–34: Alexander's family is usurped; Juliana infiltrates the manor, uncovers poisoning, is framed for witchcraft, put in a dungeon and put on trial.
- Ep 35–45: Alexander returns as the Duke, storms the wedding, frees Juliana.
- Ep 46–50: marriage declared invalid; Catherine schemes with Father Thomas.

## Brand-safety flags
Torture (branding iron, Ep 31–32), a child threatened (Ep 33), sexual content (Ep 49–50). Promos must pass platform ad policies → the tool needs a safety check.

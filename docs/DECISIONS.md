# Decision log

Format: decision → why → alternatives rejected. Add a new entry every time we choose something.

---

### D1 — Problem 1 (Find the Promos)
- **Why**: it is Kuku's own daily problem; the data is given and clean; output is checkable against the script; many constraints can be checked by code; the interview re-run (a new script in the same format) is low-risk.

### D2 — The LLM never writes timestamps
- **Why**: LLMs misquote numbers. Code gives every block an ID (`E07-B023`); the LLM only picks IDs; code converts IDs back to exact timestamps. Every output timestamp is therefore guaranteed to exist in the script.
- **Rejected**: asking the LLM directly for "start 01:12, end 01:50". It's easy to do but can't be trusted.

### D3 — Hybrid pipeline: code for structure and rules, LLM for judgement
| Step | Who | Why |
|---|---|---|
| Parse scripts | Code | Deterministic; the format is regular |
| Find hook & cliffhanger moments | LLM | Needs understanding (see the keyword failure in FINDINGS) |
| Build 20–60 s windows, snap to clean cuts | Code | Arithmetic + hard rules |
| Judge each promo cold (standalone? safe?) | LLM | Needs understanding |
| Validate (duration, order, bounds) | Code | Must never be wrong |
| Rank + de-duplicate | Code (weighted score) | Transparent, tunable |

### D4 — The "cold viewer" judge
- **Why**: "makes sense on its own" is the hardest criterion. The judge LLM sees **only the clip's text**, with no show context, the same way a stranger scrolling TikTok would. If it can't tell who is who or what's at stake, the clip fails.

### D5 — Baseline to beat: "last 45 s of every episode"
- **Why**: every episode ends on a cliffhanger, so this cheap baseline already satisfies one of the three criteria. Our tool must show it does better on the hook and standalone criteria; otherwise it isn't adding value.

### D6 — Model is swappable
- **Why**: the brief says they may plug in stronger models. One `llm.py` with a provider switch via config/env; prompts kept in separate files; responses cached so re-runs are free and reproducible.
- **Default model**: Gemini (free tier via Google AI Studio). It has a long context, and the whole show without CAMERA blocks (~43k tokens) fits in one call if needed.

### D7 — Confidentiality
- The input pack is never committed. `data/` is in `.gitignore`; the README says where to put the files.

---
## Assumptions (brief was silent)
- A1: The screenplay timestamps match the final edited video.
- A2: "Hook in first 3 s" = a striking line, action or reveal starting within 3 s of the promo's first frame.
- A3: Multi-segment promos may join moments from different episodes; each segment keeps its own episode + timestamps.
- A4: Promos should send viewers to Episode 1, so an earlier source episode is a small ranking bonus (less "catch-up" needed).
- A5: Scenes from the Duke reveal are allowed because the title already promises it.

### D8 — Parser keeps CAMERA blocks
- **Why**: visual hooks (slap close-ups, "cut to black") exist only in CAMERA lines. We can drop them later to save tokens; we can't get them back if the parser discards them.

### D9 — Parsed script goes to `build/` (gitignored), not `outputs/`
- **Why**: the parsed JSON contains the full confidential script. `outputs/` is committed and holds only the final promo results.

### D10 — One promo format + one validator for every method
- **Why**: the baseline and the AI pipeline are judged by identical rules, so comparisons are fair. Segments are stored as block IDs only; all times are derived by code.

### D11 — Hard vs soft checks
- **Hard** (reject): IDs exist, 20–60 s, no cut mid-dialogue-line, no overlap, hook/cliffhanger inside the clip.
- **Soft** (flag): hook in first 3 s, cliffhanger in last 5 s. Soft checks are structural (a hook *exists*), not quality (a hook is *good*); quality is judged later.

### D12 — Baseline = last ~45 s of each episode, frozen
- **Why**: every episode ends on a written cliffhanger, so this is the strongest "no-AI" approach. Frozen so it stays a fair yardstick.

### D13 — Committed outputs quote only hook and cliffhanger lines
- **Why**: outputs/ is public; the script is confidential.

### D14 — One OpenAI-compatible client for every model
- **Why**: Gemini, Groq, OpenRouter, Ollama and OpenAI all speak the OpenAI API. Swapping models = changing `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` in `.env`, no code change.
- **Rejected**: the Gemini-specific SDK (locks us to one vendor).

### D15 — Disk cache + rate limiter + usage log
- **Why**: free tier ≈ 10 requests/min and ~250/day. The cache makes re-runs free and outputs reproducible; the usage log gives real token numbers for the cost-at-scale estimate.
- **Note**: free-tier prompts may be used by Google for product improvement. Fine for this assignment (Kuku allows AI tools on the pack); production would use a paid tier.

### D16 — Fail loudly
- Invalid JSON → one repair retry → error. A truncated answer → error. Never return an empty or partial result as if it were real.

### D17 — Beats: one LLM call per episode; generous now, strict later
- **Why**: focused attention on a 2-min script; 50 calls fits the free tier; per-episode cache means a new episode costs one call. Up to 5 hooks / 5 cliffhangers per episode; the judge filters later.

### D18 — Anchored 1–5 scores ("most moments are 2–3")
- **Why**: without anchors, LLMs inflate scores and ranking becomes meaningless.

### D19 — Gold checks in `evals/<show>.json`, written by a human
- **Why**: human labels from our study (Ep 7/10/19 resolved endings, Ep 23 visual cliffhanger, Ep 1 strong hook) become automatic pass/fail checks. A new show gets its own file; the code stays generic.

### D20 — Pilot before full run
- **Why**: 3 calls to catch prompt problems before spending 50.

### D21 — Beat scores pick candidates; they never rank promos
- **Evidence (pilot)**: all 23 IDs were correct and the moment choices were strong, but scores were inflated (all hooks 4–5) and `context_needed: "none"` was wrong for E07-B042 and E23-B045, because the model knew the story.
- **Decision**: beat scores only filter candidates. The final ranking comes from a cold-viewer judge that sees only the clip text and compares clips side by side (comparison is more reliable than absolute scores).
- **Also**: the E01 "top hook ≥ 4" gold check is too lenient to count as evidence.

### D22 — Two kinds of clip: single stretch + bridge across episodes; flash-forward deferred
- **Why**: each episode picks up immediately from the previous one, so N → N+1 plays continuously. The bridge drops N's silent tail / cut-to-black. Flash-forward cold opens (used by real apps) are harder to get right; listed as future work.

### D23 — Cold-viewer judge: clip text only, 8 per batch, 2 rounds
- **Why**: the beat model knew the story, so it misjudged "context needed". The judge sees no IDs, episode numbers or logline, and only knows names spoken aloud. Batches allow comparison; two rounds with different batch-mates reduce luck; their disagreement measures judge noise.

### D24 — Baseline judged by the same judge
- **Why**: turns "our promos look good" into a measured comparison. Baselines are batched only with baselines.

### D25 — Switch to Claude API (Haiku 5.5); Gemini kept as fallback
- **Why**: Gemini free tier = 20 requests/day, and new accounts can't use 2.5-flash. The project needs ~95 calls.
- **How**: Anthropic's OpenAI-compatible endpoint, so `llm.py` stays the same design; switching = `.env` change. Two compatibility fixes: no `response_format` (json_object → 400) and no `temperature` (< 1 → 400 on Claude 4.7+).
- **Model**: Haiku 5.5 everywhere (~$0.25 for the full show). The judge can be upgraded to Sonnet via `LLM_MODEL_JUDGE` only if the judge's own consistency metric says it's needed.
- **Guardrails**: a spend log with cost per call, a $6 budget cap, and `--spend`.
- **Kept**: 19 episodes of gemini-2.5-flash beats (archived) for a model comparison.
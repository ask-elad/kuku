# Task 04 — AI marks hook and cliffhanger moments ("beats")

## Goal
For every episode, one LLM call marks candidate **hooks** and **cliffhangers** by block ID.
Code validates every answer. No promo building in this task (that is Task 05).

The prompt is **already written**: `prompts/beats.md`. Use it as is. If you think it needs a
change, **stop and ask**; don't edit it yourself.

## Part A — Script formatter: `src/promo_finder/scriptfmt.py`
`format_blocks(blocks) -> str`. One line per block, in file order:
```
E01-B008 | 00:11.30–00:13.10 | DIALOGUE | MATRIARCH (Cold, Commanding): You should turn around, Juliana.
E01-B001 | 00:00.00–00:04.80 | CAMERA | Symmetrical framing on the heavy church doors...
```
- DIALOGUE shows `label_raw` (speaker + delivery) then the text. Other types show only the text.
- Insert a line `== SCENE E01-S01: INT. CATHEDRAL – DAY ==` before each scene's first block.
- Keep CAMERA text in full (decision D8). Task 05 reuses this formatter for clips.

## Part B — Beats: `src/promo_finder/beats.py`
CLI: `python -m promo_finder.beats "<show folder>" [--episodes 1,7,23]`
(default: all episodes, in order).

For each episode:
1. `complete_json("beats", {episode, logline, continuity, script}, tag="beats:E07")`.
2. **Validate the response** (code, not the model):
   - Top level: `hooks` and `cliffhangers` are lists; `ending` is an object. Missing or wrong →
     treat as empty and record an error for this episode.
   - Per item: required fields are present; `type` is in the allowed list; scores are ints from 1 to 5.
     A bad item → dropped and counted as `invalid_item`.
   - `block_id` must exist **and belong to this episode**. Otherwise → dropped and counted
     as `invalid_id` (these are the "made-up IDs"; log the bad ID).
   - Duplicate block IDs within a list → keep the first.
   - Keep at most 5 per list, in the model's order.
3. Enrich each kept item from the parsed show (not from the model): `block_type`, `start`,
   `end`, and for hooks a `clean_start` = the latest clean cut point (no DIALOGUE block
   straddling it, same rule as the validator) at or before the hook block's start, **and no more
   than 3.0 s before it**. If there is none → `clean_start: null` (the hook can't open a promo
   cleanly; keep it but flag it).

Outputs (committed; they contain no script text except the model's short `why` / `open_question`):
- `outputs/<slug>/beats/beats.json`: per episode, the validated items + ending + errors
- `outputs/<slug>/beats/beats_report.md`: the report below

If the LLM call fails for one episode (`LLMError`): record the error for that episode,
**continue with the others**, and list the failures in the report. A re-run only re-calls the
failed ones (everything else is cached).

## Part C — Report (`beats_report.md`, also printed in short)
1. Totals: episodes done/failed, hooks and cliffhangers kept, `invalid_id` and `invalid_item`
   counts, **made-up ID rate** = invalid_id / all IDs returned.
2. The distribution of hook types, and of stop_power and tension scores.
3. Table: episode → number of hooks, best stop_power, number of cliffhangers, best tension, ending_type.
4. Hooks with `clean_start: null` (count + IDs).
5. Cliffhanger block types (how many are CAMERA / SOUND_FX / DIALOGUE / ACTION).
6. Tokens and calls for this run (rows in `logs/llm_usage.csv` since the run started,
   with the cached vs uncached split).
7. **Eval results** (Part D).

## Part D — Gold checks: `evals/<slug>.json` + `src/promo_finder/eval_beats.py`
Show-specific expectations live in a data file, **not in code**, so a new show just gets its own
file. Create `evals/i-married-a-broken-soldier-he-was-a-duke.json` (committed) with:
```json
{
  "resolved_or_soft_endings": [7, 10, 19],
  "min_top_hook_power": [{"episode": 1, "min": 4}],
  "cliff_types_near_end": [{"episode": 23, "types": ["CAMERA", "SOUND_FX"], "within_last_s": 8.0}]
}
```
Checks:
- `resolved_or_soft_endings`: those episodes must have `ends_on_cliffhanger: false`.
- `min_top_hook_power`: the episode's best hook stop_power ≥ min.
- `cliff_types_near_end`: the episode's **top** cliffhanger is one of these types and ends within
  the last N seconds of the episode.
Print PASS/FAIL per check, with the actual value. If the evals file is missing, skip with a note.
`python -m promo_finder.eval_beats "<show folder>"` runs them alone; the beats CLI runs them at the end.

**Never change the prompt or the evals file to make a check pass.** Report what happened.

## Tests: `tests/test_beats.py` (fake LLM, no network)
1. Formatter: scene lines, dialogue label, block order.
2. A made-up ID and an ID from another episode → dropped and counted as invalid_id.
3. A bad type or a score out of range → dropped as invalid_item.
4. Duplicates removed; at most 5 kept.
5. `clean_start` logic: a hook in the middle of a speech gets the right earlier cut point, or null if
   it's more than 3 s back.
6. An LLMError on one episode doesn't stop the others.
7. Eval checks: PASS and FAIL cases on fake beats.

## How to run (in this order)
1. Tests pass.
2. **Pilot run on 3 episodes only**: `--episodes 1,7,23`. Paste the report into Result and
   **stop**. The human reviews it before the full run.
3. The full run happens only after the human says go.

## Out of scope
- Building promos, judging, ranking
- Changing `prompts/beats.md` or the evals file

## Definition of done (for this session = the pilot)
- [ ] All tests pass
- [ ] Pilot on episodes 1, 7, 23 done; report written; eval results shown
- [ ] `git status`: `outputs/.../beats/`, `evals/` and `prompts/beats.md` appear; no `data/`, `build/`, `cache/` or `logs/`

## Result
- > **Note (D25):** The runs below were on Gemini (2.5-flash pilot + 19 episodes, archived in `beats__gemini-2.5-flash/`). They stopped at the free-tier quota. The final run is on Claude Haiku 5.5. See Task 03b and the updated report below.

### Files built
- `src/promo_finder/scriptfmt.py` — `format_blocks(blocks, scenes=None) -> str`
- `src/promo_finder/beats.py` — CLI + `_validate_response`, `_find_clean_start`, `run_beats`
- `src/promo_finder/eval_beats.py` — `run_evals` + standalone CLI
- `evals/i-married-a-broken-soldier-he-was-a-duke.json` — eval spec
- `tests/test_beats.py` — 27 tests (all pass)

### How to run
```
PYTHONPATH=src .venv/bin/python -m promo_finder.beats "data/raw/I Married a Broken Soldier. He was a Duke" --episodes 1,7,23
```

### Pilot report (episodes 1, 7, 23)

| Metric | Value |
|---|---|
| Episodes done | 3 |
| Episodes failed (LLMError) | 0 |
| Hooks kept | 13 |
| Cliffhangers kept | 11 |
| invalid_id | 0 |
| invalid_item | 0 |
| Made-up ID rate | 0.0% (0/24) |

**Tokens this run:** 23,593 total (prompt 14,267 + completion 1,751 + 7,575 thinking)
(3 uncached calls; note Gemini 2.5 Flash charges hidden thinking tokens, so total > prompt+completion)

**Per-episode summary:**

| Episode | Hooks | Best stop_power | Cliffs | Best tension | ending_type |
|---|---|---|---|---|---|
| E01 | 5 | 5 | 5 | 5 | cliffhanger |
| E07 | 4 | 5 | 2 | 4 | soft |
| E23 | 4 | 5 | 4 | 5 | cliffhanger |

**Hook types (all 13):** humiliation×5, shocking_line×4, threat×2, reveal×2
**Stop power:** all 4 or 5 — the model is not using 1–3 at all on this pilot set.
**clean_start: null:** 0 hooks flagged.
**Cliffhanger block types:** DIALOGUE×5, CAMERA×4, SOUND_FX×2 — model correctly uses CAMERA/SOUND_FX.

### Eval results (pilot)
- **PASS** `resolved_or_soft_endings E07` — `ends_on_cliffhanger=False` ✓
- **SKIP** `resolved_or_soft_endings E10` — not in pilot
- **SKIP** `resolved_or_soft_endings E19` — not in pilot
- **PASS** `min_top_hook_power E01` — best stop_power=5 ≥ 4 ✓
- **PASS** `cliff_types_near_end E23` — top cliff is CAMERA, end=02:11.50 (last 0.0s, i.e. final block) ✓

### Observations
1. **Score inflation:** model scores every hook 4 or 5. No 1–3 scores in this 3-episode pilot. May improve with a full run, or the episodes are genuinely strong.
2. **0 invalid IDs** out of 24 returned — Gemini 2.5 Flash copies IDs faithfully.
3. **Cliffhangers use all block types** (DIALOGUE, CAMERA, SOUND_FX) as expected from the data findings.
4. E07 correctly identified as soft/resolved ending (matches FINDINGS.md note about Ep 7).

### Open questions
- Will score inflation persist across all 50 episodes, or is it specific to these strong early/late-middle episodes?
- Should the full run proceed? (Awaiting human go-ahead per task instructions.)

---

## Full run — Claude Haiku 5.5, all 50 episodes

### Totals

| Metric | Value |
|---|---|
| Episodes done | 50 / 50 |
| Episodes failed (LLMError) | 0 |
| Hooks kept | 201 |
| Cliffhangers kept | 88 |
| invalid_id | 0 |
| invalid_item | 0 |
| Made-up ID rate | 0.0% (0/290) |
| Hooks with clean_start: null | 0 |

### Token usage & cost

| Metric | Value |
|---|---|
| Calls | 50 |
| Cached | 3 (the 3 pilot episodes) |
| Uncached | 47 |
| Prompt tokens | 305,626 |
| Completion tokens | 82,887 |
| Total tokens | 388,513 |
| **Total spend** | **$0.0720** |

### Distributions

**Hook types (201 total):** shocking_line×54, reveal×46, threat×32, humiliation×23, slap_or_violence×12, other×10, action×9, rescue×8, romance×7

**Stop power:** 5→30, 4→113, 3→55, 2→3, 1→0 — score inflation mostly resolved; the full run shows the 3s and a few 2s that were absent from the pilot.

**Tension:** 5→19, 4→33, 3→30, 2→6, 1→0

**Cliffhanger block types:** DIALOGUE×43, CAMERA×31, SOUND_FX×9, ACTION×5

### Eval results (all 5 gold checks — 5 PASS, 0 FAIL)

- **PASS** `resolved_or_soft_endings E07` — `ends_on_cliffhanger=False` ✓
- **PASS** `resolved_or_soft_endings E10` — `ends_on_cliffhanger=False` ✓
- **PASS** `resolved_or_soft_endings E19` — `ends_on_cliffhanger=False` ✓
- **PASS** `min_top_hook_power E01` — `best_stop_power=5` ≥ 4 ✓
- **PASS** `cliff_types_near_end E23` — `type=CAMERA, end=02:11.50` ✓

### Observations

1. **Zero invalid IDs across all 290 returned** — Claude Haiku follows the block-ID format perfectly.
2. **Score inflation reduced but not gone:** 3s appear (55 hooks), and a few 2s (3 hooks). Still no 1s.
3. **E06 and E08 are outliers** — only 2–3 hooks, best stop_power 3, 1 cliffhanger — genuinely quieter episodes.
4. **Cliffhangers skew DIALOGUE (43/88)** — the model uses CAMERA/SOUND_FX when available but most episode endings fall on spoken lines.
5. **Cost: $0.072 for 50 episodes** (~$0.0014/episode). Well within the $6 budget.
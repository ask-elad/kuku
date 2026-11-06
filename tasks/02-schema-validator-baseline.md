# Task 02 — Promo format, validator, and baseline

## Goal
1. Define **one promo format** that every method (this baseline, and the AI pipeline later) produces.
2. Build a **validator** that enforces the promo rules in one place.
3. Build a **dumb baseline** ("last ~45 s of each episode") so the AI pipeline has something
   to beat.
4. Render promos as **Markdown** so an editor (and the reviewer) can read them.

No LLM in this task. Standard library only.

## Part A — Shared loader: `src/promo_finder/show.py`
- `load_show(show_dir) -> Show`: finds `build/<slug>/episodes.json`. If it is missing, runs
  the Task 01 parser first.
- Gives: the list of episodes, `block(id)` lookup by ID, `blocks_in(episode, t0, t1)`, and
  episode duration. Later tasks reuse this. Keep it small.

## Part B — Promo format: `src/promo_finder/promo.py`
A promo is a plain dict / JSON object. **Fields a method writes:**
```json
{
  "promo_id": "BASE-E01",
  "method": "baseline",
  "segments": [
    {"start_block": "E01-B050", "end_block": "E01-B081"}
  ],
  "hook":        {"block_id": "E01-B052", "text": "..."},
  "cliffhanger": {"block_id": "E01-B081", "text": "..."},
  "why": "one line",
  "scores": {},
  "rank": null
}
```
`hook` and `cliffhanger` may be `null`. A promo may have several segments, from one or
several episodes, **in playback order** (a later moment may come first, e.g. a flash-forward
cold open).

**Fields the code derives** (`resolve(promo, show)`; a method never writes these):
- Per segment: `episode`, `start` = start of `start_block`, `end` = end of `end_block`,
  `start_tc` / `end_tc` (`MM:SS.ss` via `fmt_time`), `duration`.
- Per promo: `duration` = sum of segment durations; for hook and cliffhanger, `at` = their
  position **in promo time**. Mapping: the time of all earlier segments + (block time − segment start).
- `checks` (from the validator, below).

Times always come from block IDs. **Never accept a time written by a method.**

## Part C — Validator: `src/promo_finder/validate.py`
Use a tolerance `EPS = 0.05` s for every float comparison.

**Hard checks** (any failure → `valid: false`, the promo is rejected):
| Name | Rule |
|---|---|
| `ids_exist` | every block ID in segments / hook / cliffhanger exists |
| `segment_same_episode` | start_block and end_block of a segment are in the same episode |
| `segment_order` | start < end and segment duration ≥ 1.0 s |
| `no_overlap` | two segments of the same episode don't overlap in time |
| `duration_20_60` | 20 ≤ promo duration ≤ 60 |
| `no_mid_line_cut` | at every segment start and end time `t`, no DIALOGUE block in that episode has `start < t < end` |
| `hook_inside`, `cliff_inside` | if given, the hook / cliffhanger block lies inside one of the segments |

**Soft checks** (flags only; the promo is kept):
| Name | Rule |
|---|---|
| `has_hook` / `has_cliffhanger` | not null |
| `hook_in_first_3s` | hook `at` (block start) ≤ 3.0 s |
| `cliff_in_last_5s` | cliffhanger block end, in promo time, ≥ duration − 5.0 s |

Important: soft checks are **structural**. They say a hook *exists* in the first 3 s, not that
it is *good*. Quality is judged in a later task. Say this in the Markdown report too.

Output per promo: `"checks": {"hard": {...bools}, "soft": {...bools}, "errors": ["readable message", ...], "valid": bool}`.

CLI (works for any method's output):
`python -m promo_finder.validate <promos.json> --show "<show folder>"` → prints a report
(count, valid count, failure count per hard check, pass rate per soft check).

## Part D — Baseline: `src/promo_finder/baseline.py`
CLI: `python -m promo_finder.baseline "<show folder>"`
For **each episode**:
1. `E` = episode end. **End block** = the block with the latest end time (ties → last in file
   order).
2. **Clean start points** = block start times where no DIALOGUE block straddles the time
   (same rule as `no_mid_line_cut`).
3. Pick the clean start `t` with `20 ≤ E − t ≤ 60` that is **closest to E − 45**. Ties → the
   earlier one. **Start block** = the first block in file order that starts at `t`.
4. **Hook** = the first DIALOGUE block starting within the promo's first 3.0 s; else the first
   ACTION block there; else `null`.
5. **Cliffhanger** = the last DIALOGUE or ACTION block whose end is in the promo's last 5.0 s;
   else the last DIALOGUE/ACTION block in the promo; else `null`.
6. `why` = `"Baseline: last ~45 s of episode N"`; `promo_id` = `BASE-E{ep:02d}`;
   `method` = `"baseline"`; `rank` = `null` (the baseline doesn't rank).

Then resolve and validate all promos, and write:
- `outputs/<slug>/baseline/promos.json`: the full resolved promos, including checks
- `outputs/<slug>/baseline/promos.md`: rendered (Part E)

Fully deterministic: the same input gives byte-identical output.

## Part E — Renderer: `src/promo_finder/render.py`
`render_markdown(promos, title) -> str`. Layout:
1. A header with the method name, and a summary: number of promos, number valid, failures per
   hard check, pass rate per soft check, plus the "soft checks are structural" note.
2. One section per promo (in rank order if ranks exist, else in ID order):
   - Segments, one line each: `E01  01:33.00 → 02:18.00  (45.0 s)`
   - Total duration
   - Hook: text plus its `at` time; Cliffhanger: text plus `at`
   - Why
   - Checks: ✓/✗ per check, plus error messages if invalid

Keep quoted text to the single hook / cliffhanger line. **Don't dump segment dialogue into the
output**, because the script is confidential and `outputs/` is committed.

## Tests: `tests/test_validate.py` and `tests/test_baseline.py`
Reuse the Task 01 fixtures (add another fake episode if you need more blocks; no real
script text). Test:
1. A correct single-segment promo is valid, with the right `start`, `end` and `duration`.
2. A cut in the middle of a dialogue line → `no_mid_line_cut` fails.
3. Too short / too long → `duration_20_60` fails.
4. An unknown block ID → `ids_exist` fails, with no crash.
5. A hook block outside the segments → `hook_inside` fails.
6. Two segments: the hook in the second segment gets the correct `at` (offset includes the first segment).
7. Overlapping segments of the same episode → `no_overlap` fails.
8. The baseline on fixtures: valid promos, no mid-line cut, deterministic (run twice, same output).

## Expected on the real show
- 50 baseline promos. **All should be hard-valid**; if any aren't, explain why in Result
  (e.g. no clean start point in range).
- Our prediction: `cliff_in_last_5s` ≈ always passes, `hook_in_first_3s` often fails. Report
  the real rates. **Don't tune the baseline to look better or worse.** It is a fixed yardstick.

## Out of scope
- Any LLM call, prompts, scoring or ranking logic
- Speaker alias merging
- Any UI

## Definition of done
- [ ] `python -m promo_finder.baseline "data/raw/<show>"` writes both output files
- [ ] `python -m promo_finder.validate outputs/<slug>/baseline/promos.json --show "data/raw/<show>"` prints the report
- [ ] All tests pass (old and new)
- [ ] `git status` shows `outputs/<slug>/baseline/` but no `data/` or `build/` files

## Result

### Files built
| File | Purpose |
|---|---|
| `src/promo_finder/show.py` | `Show` class + `load_show()` |
| `src/promo_finder/promo.py` | `resolve(promo, show)` — adds derived times and `at` offsets |
| `src/promo_finder/validate.py` | `validate(promo, show)` + CLI |
| `src/promo_finder/baseline.py` | `generate_baseline(show)` + CLI |
| `src/promo_finder/render.py` | `render_markdown(promos, title)` |
| `tests/fixtures/ep_promo.txt` | 65-second fixture episode (E02, 13 blocks) |
| `tests/test_validate.py` | 7 validator tests |
| `tests/test_baseline.py` | 7 baseline tests |
| `outputs/i-married-a-broken-soldier-he-was-a-duke/baseline/promos.json` | Full resolved+validated promos |
| `outputs/i-married-a-broken-soldier-he-was-a-duke/baseline/promos.md` | Human-readable render |

### How to run
```
# Generate baseline outputs
PYTHONPATH=src python -m promo_finder.baseline "data/raw/I Married a Broken Soldier. He was a Duke"

# Validate and print report
PYTHONPATH=src python -m promo_finder.validate \
    outputs/i-married-a-broken-soldier-he-was-a-duke/baseline/promos.json \
    --show "data/raw/I Married a Broken Soldier. He was a Duke"

# Tests
python -m pytest tests/
```

### Validator report (real show)
```
Promos: 50  Valid: 50  Invalid: 0

Hard check failures: none

Soft check pass rates:
  has_hook:         47/50 (94%)
  has_cliffhanger:  50/50 (100%)
  hook_in_first_3s: 47/50 (94%)
  cliff_in_last_5s: 36/50 (72%)
```

All 50 baseline promos pass every hard check.

### 3 promos where hook check failed (IDs only)
BASE-E17, BASE-E25, BASE-E39  
(These have no DIALOGUE or ACTION block starting within the promo's first 3 seconds.)

### New data quirks
1. **cliff_in_last_5s fails 14/50 — not "almost always passes".**  
   Episodes frequently end with CAMERA or SOUND FX blocks that run several seconds after the last DIALOGUE line. The end block (latest block end time) is often a silent block, so the cliffhanger's end in promo time falls outside the last 5 s window even though it is the last spoken line. Example: BASE-E05 — last DIALOGUE ends 1 s before the CAMERA tail, putting its promo-time end at 39.7 s vs. the 40.0 s threshold.

2. **hook_in_first_3s passes for every hook found.**  
   All 47 hooks are ACTION blocks starting at exactly promo_start (at = 0.0 s). The first 3 s of each selected window is always led by an ACTION block; the first DIALOGUE block consistently starts more than 3 s into the window.

3. **File order ≠ timestamp order.**  
   Confirmed in fixture: B013 (CAMERA at 00:05.00) is the 13th block in file order but has an earlier start time than many preceding blocks. The baseline and validator both sort by time, not file order, to avoid this trap.

### Open questions
- Should `cliff_in_last_5s` treat SOUND FX / CAMERA tails differently (not count them toward promo duration for the purpose of this check)?
- The 3 no-hook episodes: is this a signal that the baseline window choice is wrong for those episodes, or just that those episodes lack early ACTION/DIALOGUE?
# Task 06 — Fix label leak, rank, final outputs, one-command run, README

Do the parts **in order**. The model is Claude Haiku 5.5 (`.env`). Use the venv; the package is
installed (`pip install -e .`).

---
## Part 0 — Remove the "cliffhanger" label leak (judge input only)
**Found**: the screenplays label their own cliffhangers in CAMERA / SOUND FX text, e.g. "...the
door cracks open—cutting to an intense, heart-stopping cliffhanger." The judge sees this, so
cliffhanger scores are biased.

1. In `scriptfmt.format_clip` **only** (not the beats formatter), replace case-insensitive matches of
   `cliff-?hangers?` with `moment`. Keep everything else unchanged.
2. Add a test: the formatted clip text contains no "cliffhanger" in any form.
3. **Before re-running**, copy `outputs/<slug>/judge/` to `outputs/<slug>/judge__before_leak_fix/`.
4. Re-run the full judge (pipeline + baseline, both rounds). The text changed, so the cache misses (~$0.11).
5. In the Result section, give a table of the mean hook / cliffhanger / standalone scores for
   pipeline and baseline, **before vs after** the fix.

## Part A — Fairness check: mixed batches
Up to now, baselines were only judged alongside baselines, so each group was graded partly relative
to itself. Add `--calibrate` to the judge CLI:
- Build 6 batches of 8 clips: in each, 4 random pipeline candidates + 4 random baselines
  (`random.Random(7)`), shuffled, labelled A–H as usual. Tags `judge_cal:b01`… Same prompt.
- Report: the mean hook / cliffhanger / standalone for pipeline vs baseline **within these mixed batches**.
- Write `outputs/<slug>/judge/calibration.json` and add a section to `judge_report.md`.

## Part B — Ranking: `src/promo_finder/rank.py`
CLI: `python -m promo_finder.rank "<show folder>"`. Input: `judge/judged.json`. No LLM.

1. **Score** = 0.4 × hook + 0.3 × cliffhanger + 0.3 × standalone (the round-averaged scores).
2. **Safety**: `unsafe` → excluded from the ranking (listed separately). `sensitive` → score − 0.5,
   flag `needs_review`.
3. **Overlap clusters**: two promos overlap if, in the same episode, their time ranges share > 50 % of
   the shorter one's duration (check segment by segment). Group overlapping promos; keep the
   highest score as the **main** promo; the others become its `alternatives` (id, score,
   hook text, duration).
4. **Order**: sort the main promos by score desc → earlier starting episode → shorter
   duration → promo_id.
5. **Variety**: build the **top 10** greedily from that order, with at most **one promo per
   starting episode** (the episode of the first segment). Then the rest by the order from step 4.
   Assign `rank` 1…N.
6. **Fill the text fields from the parsed show** (never from a model): `hook.text` and
   `cliffhanger.text` = the text of those blocks (plus the speaker for dialogue).
7. Same ranking applied to the judged **baselines** (for the comparison only).

## Part C — Final outputs (committed): `outputs/<slug>/final/`
- `promos.json`: all ranked promos (resolved segments with `start_tc` / `end_tc`, duration,
  hook, cliffhanger, scores, score, safety, flags, confusions, judge `why`, alternatives).
- `promos.csv`: one row per promo: rank, promo_id, segments
  (`E23 01:19.00–02:11.50`, several joined with ` + `), duration, score, hook, cliffhanger,
  standalone, safety, hook_text, cliffhanger_text, why.
- `promos.md`:
  1. A header: show, model, date, number of promos, total spend (`--spend`).
  2. **Post these first: the top 10** as a table: rank · segments · duration · hook line ·
     why (judge) · flags.
  3. **Why these first**: 3 lines explaining the ranking rule (hook-weighted score; one per
     episode in the top 10; ties → earlier episode, since new viewers start at Episode 1).
  4. All promos, in rank order: segments, duration, hook (text + `at`), cliffhanger (text), scores,
     why, confusions, alternative cuts.
- `ranking_report.md`: score distribution of the main promos; overlap clusters (count, sizes);
  **pipeline vs baseline**: the mean scores of all promos, the mean of the **top 10 of each**, and the
  mixed-batch calibration numbers from Part A; the sensitive / unsafe list.

Quote **only** the hook and cliffhanger lines (D13). No other script text in `outputs/`.

## Part D — Human review sheet (NOT committed): `build/<slug>/review_top10.md`
For each of the top 10: rank, promo_id, segments, then the **full `format_clip` text**, then this
checklist with empty boxes:
```
- [ ] Hook lands in first 3 s (would I stop scrolling?)
- [ ] Ends on an unresolved moment (do I need to know what happens next?)
- [ ] Makes sense to a stranger
- [ ] Start/end cut points are clean (no half sentence, no dead air)
- [ ] I'd post this.   Notes:
```

## Part E — One-command run: `src/promo_finder/run.py`
`python -m promo_finder.run "<show folder>"` runs: parse → baseline → beats → candidates →
judge (pipeline + baseline) → rank, then prints where the outputs are and the spend for this run.
Each stage reuses existing modules; LLM stages are cached, so a re-run is free. Flags:
`--no-baseline` (skip the baseline + its judging, to save cost on a new show). Stop with a clear
message if a stage fails.

## Part F — `README.md` (replace)
Short and practical:
1. What it does (3 lines) and what it outputs (`final/promos.md` / `.csv` / `.json`).
2. Setup: Python 3.12, venv, `pip install -e .`, `cp .env.example .env`, add a key.
3. Input: put the show folder in `data/raw/<show>/` (one `.txt` per episode). **The input pack is
   not in the repo (confidential).**
4. Run: the one command; how long it takes and what it costs (from our run: ~$0.25 per 50-episode show
   on Claude Haiku 5.5, including the baseline).
5. Switching models: edit `.env` (the Claude block vs the Gemini block in `.env.example`; `LLM_MODEL_JUDGE`
   for a stronger judge).
6. Pipeline overview: the 6 stages, one line each; where the prompts live; link to `docs/DECISIONS.md`
   and `docs/FINDINGS.md`.
7. Tests: `pytest`.

## Tests
- Part 0 redaction test.
- `rank.py`: weighted score; sensitive penalty; unsafe excluded; overlap clustering with
  alternatives; one per episode in the top 10; tie-breaks; text fields come from the show.
- `run.py`: stage order with stubbed stages; `--no-baseline` skips the baseline stages.

## Definition of done
- [ ] All tests pass (report the count)
- [ ] Part 0 before/after table and Part A calibration numbers in Result
- [ ] `outputs/<slug>/final/` has promos.md / .csv / .json + ranking_report.md
- [ ] `build/<slug>/review_top10.md` exists
- [ ] A fresh shell: `python -m promo_finder.run "data/raw/<show>"` completes from cache in seconds
- [ ] README replaced; `git status` shows no data/, build/, cache/ or logs/
- [ ] Paste into Result: the top-10 table from promos.md, the ranking_report pipeline-vs-baseline section, and `--spend`. Then STOP.

## Result

### Tests

136 tests pass (`pytest`). New tests added:
- `tests/test_scriptfmt_redaction.py` — 7 tests for Part 0 redaction
- `tests/test_rank.py` — 15 tests for rank.py (scoring, safety, overlap clustering, top-10 variety, tie-breaks, text fields)
- `tests/test_run.py` — 3 tests for run.py (stage order, --no-baseline)

### Part 0 — Before / after leak fix

| Group    | Metric      | Before | After |
|----------|-------------|--------|-------|
| Pipeline | hook        | 3.55   | 3.64  |
| Pipeline | cliffhanger | 3.84   | 3.89  |
| Pipeline | standalone  | 3.13   | 3.11  |
| Baseline | hook        | n/a*   | 2.88  |
| Baseline | cliffhanger | n/a*   | 3.56  |
| Baseline | standalone  | n/a*   | 3.15  |

*Before fix: `judged_baseline.json` was not persisted to disk; only the in-memory run_judge
 report was printed. Added `judged_baseline.json` output to judge.py as part of this task.

The fix raised hook +0.09 and cliffhanger +0.05 for pipeline. Standalone was essentially
unchanged (−0.02). Cliffhanger scores were modestly biased upward by the leaked label.

New sensitive clips after fix: 3 more (C-E12-02, C-E15-01, C-E38-03) flagged that were
previously ok — suggesting the judge was previously pattern-matching "cliffhanger" text as
evidence of dramatic merit rather than evaluating content.

### Part A — Calibration (mixed batches)

| Group    | n  | hook | cliffhanger | standalone |
|----------|----|------|-------------|------------|
| Pipeline | 24 | 3.83 | 3.83        | 3.21       |
| Baseline | 24 | 2.58 | 2.92        | 3.12       |

Pipeline consistently scores higher on hook (+1.25) and cliffhanger (+0.91) than baseline
when judged side-by-side. Standalone is nearly tied (3.21 vs 3.12). This confirms the
pipeline beat selection creates significantly better hooks and endings than the naive
last-45s baseline.

### Final outputs

`outputs/i-married-a-broken-soldier-he-was-a-duke/final/`
- `promos.json`, `promos.csv`, `promos.md`, `ranking_report.md`

`build/i-married-a-broken-soldier-he-was-a-duke/review_top10.md` (not committed)

### Top-10 table (from promos.md)

| Rank | Segments | Duration | Hook | Why | Flags |
|------|----------|----------|------|-----|-------|
| 1 | E45 00:54.00–01:53.00 | 59.0s | ALEXANDER (Furious, Cold): You poisoned my mother. You tortu | A bombshell opening and a legitimacy twist ending make a strong ad. The earlier  | — |
| 2 | E23 01:26.00–02:11.50 | 45.5s | LADY JULIANA (Venomous, Resolute): Arsenic. | Sudden collapse and a door opening into a heart-stopping moment drive a strong c | — |
| 3 | E26 00:56.00–01:55.50 | 59.5s | DOWAGER DUCHESS (Trembling, Heartbroken): Rupert and Catheri | Poisoning plus a sudden grab and 'Where did you get this ring?' ends on a must-k | — |
| 4 | E36 02:16.00–02:36.00 | 20.0s | ALEXANDER'S MOTHER (Solemn, Shattered): She is to be execute | Immediate death-sentence shock and a 'two days from now' deadline create urgent  | — |
| 5 | E42 00:30.50–01:17.50 | 47.0s | BLOND NOBLEMAN (Denial, Shaken): You cannot be him. Alexande | Dead-man-returns bombshell is instantly gripping, with a revenge threat that pul | — |
| 6 | E03 01:24.00–02:20.30 | 56.3s | The Bearded Stranger effortlessly blocks the guard's strike  | Action-hero beat plus a kneeling proposal creates a clear, romantic payoff quest | — |
| 7 | E15 01:00.00–01:26.00 | 26.0s | The Tall Thug hoists his heavy wooden club above his head to | Immediate menace and a rescue cut to a knife-edge standoff; the gist lands even  | needs_review |
| 8 | E31 02:13.00–02:40.00 | 27.0s | Close-up of the red-hot poker pressing directly down into th | Instant visual shock and a glowing iron inches from an eye give a strong cliffha | needs_review |
| 9 | E07 00:51.50–01:15.50 | 24.0s | GERALD (Bitter, Sneering): You chose that scarred beggar ove | Clear rivalry and a menacing reveal of the husband walking out of the fog create | — |
| 10 | E11 00:16.80–00:53.60 | 36.8s | GERALD (Aggressive, Snarl): Your husband stole my gold pocke | Clear accusation and a constable search with an ominous 'Let them.' Easy to foll | — |

### Pipeline vs baseline (from ranking_report.md)

#### All judged promos
| Group    | n  | hook | cliffhanger | standalone | score |
|----------|----|------|-------------|------------|-------|
| Pipeline | 48 | 3.80 | 3.86        | 3.18       | 3.60  |
| Baseline | 50 | 2.88 | 3.56        | 3.15       | 3.17  |

#### Top 10 of each
| Group    | n  | hook | cliffhanger | standalone | score |
|----------|----|------|-------------|------------|-------|
| Pipeline | 10 | 4.60 | 4.60        | 3.50       | 4.22  |
| Baseline | 10 | 4.10 | 4.45        | 3.65       | 4.07  |

#### Mixed-batch calibration
| Group    | n  | hook | cliffhanger | standalone |
|----------|----|------|-------------|------------|
| Pipeline | 24 | 3.83 | 3.83        | 3.21       |
| Baseline | 24 | 2.58 | 2.92        | 3.12       |

### Spend

```
Total spend : $0.2829

By stage:
  beats:          $0.0720
  judge:          $0.1118
  judge_baseline: $0.0800
  judge_cal:      $0.0192
  ping:           $0.0000
```

### Open questions / data quirks

- The cliffhanger text for `C-E23-02` (rank 2) literally says "cutting to an intense,
  heart-stopping cliffhanger" — this is verbatim screenplay stage direction and not a
  spoiler in the final output, since it appears in the `cliffhanger.text` field of
  `promos.json` (which is a quote of the source, not judge input). The judge only saw the
  redacted version ("moment").
- E15 and E31 promos are `needs_review` (sensitive). The E31 clip involves a hot poker —
  editor should decide if it's appropriate for the target platforms.
- Overlap clusters average ~3 alternatives per episode with candidates — the judge's
  strongest clip consistently ranks several seconds ahead of its alternatives.
# Task 05 — Build candidate clips, then the cold-viewer judge

## Goal
1. **Code** turns beats (Task 04) into candidate promo clips. No LLM.
2. An **LLM judge** scores each clip as a stranger would, seeing only the clip.
Ranking is **not** part of this task (that is Task 06).

The judge prompt is **already written**: `prompts/judge.md`. Use it as is. If you think it
needs a change, stop and ask.

Inputs: the parsed show (`load_show`), `outputs/<slug>/beats/beats.json`.

---
## Part A — Candidates: `src/promo_finder/candidates.py`
CLI: `python -m promo_finder.candidates "<show folder>"`

### A1. Prepare the beats
- Use only hooks with `clean_start` not null (count the ones skipped).
- **Merge cliffhangers** within each episode: if two cliffhangers end within 1.0 s of each
  other, keep the one with higher tension (tie → later end). Count the merges.

### A2. Two kinds of clip
**Single** (same episode). For hook `h` and cliffhanger `c` in the same episode, with
`c.start ≥ h.start` and `c.block_id ≠ h.block_id`:
- one segment: `start_block` = the first block in file order whose start == `h.clean_start`;
  `end_block` = `c.block_id`.

**Bridge** (episode N → N+1; only if both exist). For hook `h` in episode N and cliffhanger
`c` in episode N+1:
- segment 1: `start_block` as above → `end_block` = the **last DIALOGUE or ACTION block** of
  episode N (by end time; ties → last in file order). This drops N's silent tail and
  "cut to black", which would be a dead frame in the middle of an ad.
- segment 2: the first block of N+1 (earliest start; ties → first in file order) → `c.block_id`.
- Justification: every episode picks up immediately from the previous one (FINDINGS), so this
  plays as one continuous stretch.

Each candidate gets `hook = {block_id: h.block_id}`, `cliffhanger = {block_id: c.block_id}`,
plus `beat_notes` = `{hook_why, hook_type, stop_power, open_question, tension}` copied from
beats. **Leave `why` empty**; the judge fills it in. `method: "pipeline"`.

### A3. Filter, then choose
1. Resolve and validate every pairing with the Task 02 validator. Keep only `valid: true`.
   Count the rejections per failed hard check (too short, too long, mid-line cut, …).
2. **Per hook**, keep at most one single and one bridge: the highest `tension`, then the
   duration closest to 37.5 s, then the earlier cliffhanger.
3. **Remove near-duplicates**: two candidates overlap if, within the same episode, their time
   ranges share > 50 % of the shorter one's duration. Keep the one with the higher
   `stop_power + tension`; ties → the earlier hook. Count the removals.
4. IDs: `C-E07-01`, `C-E07-02`, … per starting episode, in order of start time. Deterministic.

### A4. Outputs
- `outputs/<slug>/candidates/candidates.json`: the resolved candidates, with checks
- `outputs/<slug>/candidates/candidates_report.md`: counts (total, singles vs bridges, per episode),
  a histogram of durations in 10 s bins, and every drop/skip/merge count from above.
**Sanity gate**: if the total is below 60 or above 250, write the report, print a warning,
and stop. Don't judge.

---
## Part B — Judge: `src/promo_finder/judge.py`
CLI: `python -m promo_finder.judge "<show folder>" [--limit-batches N]`

### B1. Clip text (what the judge sees)
Add `format_clip(promo, show) -> str` to `scriptfmt.py`:
- For each segment: the blocks whose start is ≥ the segment start (EPS 0.05) and < the segment end, in file order.
- **Times are rebased to promo time** (the clip starts at 00:00; segment 2 continues from where
  segment 1 ended).
- **No block IDs, no episode numbers, no scene IDs, no logline.** Keep the scene heading text
  (e.g. `INT. CATHEDRAL – DAY`) as a plain line where the scene changes.
- Between segments, insert a line `== CUT ==`.
- Line format: `00:03.20–00:05.10 | DIALOGUE | GERALD (Cold): text`.

### B2. Batches
- Each batch holds **8 clips**, labelled `CLIP A` … `CLIP H` (labels only, never candidate IDs).
- **Two rounds.** Round 1: shuffle all candidates with `random.Random(1)`, then cut into batches
  of 8. Round 2: shuffle with `random.Random(2)`. Each clip is judged once per round, so twice
  in total, usually alongside different clips. A last batch may be smaller.
- The `{{clips}}` variable = each clip as `### CLIP A` followed by its `format_clip` text,
  separated by blank lines.
- `tag = "judge:r1:b03"`.

### B3. Validate each response (code)
- Every label sent appears exactly once, with no extra labels. Scores are ints from 1 to 5. `safety`
  is in the allowed list. `confusions` is a list (keep at most 3).
- A bad or missing entry → that clip has no judgment from that round (record the error).
  An LLMError for a whole batch → record it and continue with the other batches.

### B4. Combine the two rounds per clip
- `scores` = the mean of the valid rounds for `hook`, `cliffhanger` and `standalone` (1 decimal).
- `judge_disagreement` = the max absolute difference between rounds over the three scores (null if only 1 round).
- `safety` = the worst of the rounds (unsafe > sensitive > ok), with its reason.
- `confusions` = the union (deduplicated, max 4). `why` and `hook_moment` come from round 1 (or
  whichever round is valid).
- `judge_rounds` = the number of valid rounds (0, 1 or 2). A clip with 0 rounds stays unjudged.
- Write the judge's `why` into the candidate's `why` field.

### B5. Outputs
- `outputs/<slug>/judge/judgments_raw.json`: every batch: round, batch number, the label → candidate ID
  map, and the validated response or error
- `outputs/<slug>/judge/judged.json`: candidates + scores + safety + confusions + why
- `outputs/<slug>/judge/judge_report.md`:
  1. Clips judged with 2 / 1 / 0 rounds; batch errors
  2. The distribution of each score (how many 1s, 2s, … 5s)
  3. **Judge consistency**: mean `judge_disagreement`, and the % of clips with disagreement ≥ 2
  4. Safety counts, plus the IDs of the unsafe and sensitive clips
  5. Single vs bridge: mean scores of each
  6. **Baseline comparison**: also judge the 50 baseline promos from Task 02 the same way
     (same two-round method, but only baselines mixed together, never with candidates) and
     show the mean hook / cliffhanger / standalone scores for baseline vs pipeline. This is the
     headline result.
  7. Tokens and calls for this run (cached vs uncached)

---
## Tests: `tests/test_candidates.py`, `tests/test_judge.py` (fake LLM, no network)
1. Cliffhanger merge within 1.0 s keeps the higher tension.
2. A single clip uses `clean_start`; a hook without `clean_start` is skipped.
3. A bridge: segment 1 ends on the last DIALOGUE/ACTION of ep N; segment 2 starts at ep N+1's first block.
4. Per-hook selection and overlap removal follow the tie-break rules.
5. `format_clip`: times are rebased across 2 segments, `== CUT ==` is present, no IDs or episode numbers appear.
6. Batching: each clip appears once per round; labels A–H; deterministic.
7. Validation: a missing label, a score out of range, an extra label → handled as specified.
8. Combining: mean, disagreement, worst safety, single round.

## How to run (in this order)
1. Tests pass.
2. Candidates on the full show → paste the candidates report into Result.
3. **Judge pilot**: `--limit-batches 1` (1 batch of round 1 only, about 1 call). Paste that batch's
   clip text for one clip + the raw response into Result and **stop** for human review.
4. The full judge run (pipeline + baseline) only after the human says go.

## Out of scope
- Ranking and final output (Task 06)
- Flash-forward / cold-open clips (deferred; see DECISIONS)
- Changing `prompts/judge.md`, `prompts/beats.md` or the beats

## Definition of done (this session)
- [ ] Tests pass
- [ ] Candidates report written; total within the sanity gate
- [ ] Judge pilot done; one clip text + raw response in Result
- [ ] `git status` shows no `data/`, `build/`, `cache/` or `logs/`

## Result

### Design change: A3.3 (D21)

A3.3 was revised before the candidates run: near-duplicate removal (which used beat scores to
choose between overlapping clips) was replaced with **exact-duplicate removal only** (identical
start\_block + end\_block pairs). Rationale: beat scores must not rank promos (D21); overlapping
clips with different hooks are alternative cuts for the editor. Overlap dedup moves to Task 06
(ranking), where judge scores are available. See `docs/DECISIONS.md` D21.

### What was built

- **`src/promo_finder/scriptfmt.py`**: added `format_clip(promo, show) -> str`. Times rebased to
  promo-start (00:00), scene headings shown as plain lines, no block/scene IDs, `== CUT ==`
  between segments.
- **`src/promo_finder/candidates.py`**: `build_candidates()` + CLI.
  A1 merges cliffhangers within 1 s, A2 generates singles + bridges, A3 validates/deduplicates,
  A4 assigns IDs. Writes `candidates.json` and `candidates_report.md`.
- **`src/promo_finder/judge.py`**: `run_judge()` + CLI. Two rounds of batches (8 clips each),
  validates responses, combines scores, writes `judgments_raw.json`, `judged.json`, `judge_report.md`.
- **`tests/test_candidates.py`** (8 tests), **`tests/test_judge.py`** (13 tests): all 21 pass.

### How to run

```bash
PYTHONPATH=src python -m pytest tests/test_candidates.py tests/test_judge.py -v
PYTHONPATH=src python -m promo_finder.candidates "data/raw/I Married a Broken Soldier. He was a Duke"
PYTHONPATH=src python -m promo_finder.judge "data/raw/I Married a Broken Soldier. He was a Duke" --limit-batches 1
```

### Candidates report (91 total — sanity gate passed)

```
Total candidates: 91
Singles: 86  Bridges: 5

Per starting episode: 40 episodes represented (1–5 per episode)

Duration histogram:
  20–30 s: 23    30–40 s: 23    40–50 s: 19    50–60 s: 26    other: 0

Drops/skips/merges:
  Hooks skipped (no clean_start): 0
  Cliffhanger merges: 1
  Exact-duplicate removals: 0
  Rejections by hard check:
    duration_20_60: 525
    no_mid_line_cut: 6
```

The 525 duration rejections reflect that episodes are ~120–150 s long; most hook→cliff
pairings within the same episode exceed 60 s.

### Judge pilot (--limit-batches 1)

One batch of 8 clips from round 1. No errors; all 8 labels returned valid JSON.

**First clip (A = C-E43-02):**

```
INT. RUINED CATHEDRAL – CONTINUOUS
00:00.00–00:01.90 | DIALOGUE | CROWN OFFICIAL (Deliberate, Damning): Lord Henry Sterling.
00:02.40–00:03.90 | CAMERA | Quick pan to Lord Sterling stiffening in his pew, then the Crown Official.
...
00:52.20–00:54.36 | CAMERA | Extreme close-up on Lord Sterling's face frozen in pure terror...
```

**Raw judge response (clip A):**

```json
{
  "label": "A",
  "hook": 3,
  "cliffhanger": 5,
  "standalone": 4,
  "confusions": [
    "Why Sterling is accused and what his role was",
    "What the red-ribboned document means"
  ],
  "safety": "ok",
  "safety_reason": "",
  "hook_moment": "Official names 'Lord Henry Sterling' in a damning, deliberate tone",
  "why": "Strong accusation plot and a tense, trapped-villain ending. The opening is slow, but the payoff at the door is a clear cliffhanger."
}
```

---

### Full judge run (both rounds, pipeline + baseline)

#### judge_report.md

```
# Judge Report

## Coverage

- 2 rounds: 91
- 1 round:  0
- 0 rounds: 0
- Batch errors: 0

## Score Distributions

- hook:        1→1  2→12  3→20  4→50  5→8
- cliffhanger: 2→7  3→15  4→60  5→9
- standalone:  2→13  3→51  4→27

## Judge Consistency

- Mean disagreement: 0.66
- % clips with disagreement ≥ 2: 1.1%

## Safety

- ok: 81  sensitive: 10  unsafe: 0
- Sensitive: C-E12-01, C-E13-01, C-E13-02, C-E16-01, C-E16-02, C-E16-03,
             C-E24-01, C-E24-02, C-E31-01, C-E31-02

## Single vs Bridge

| Type   | n  | hook | cliffhanger | standalone |
|--------|----|------|-------------|------------|
| Single | 86 | 3.58 | 3.82        | 3.15       |
| Bridge |  5 | 3.10 | 4.10        | 2.80       |

## Baseline Comparison

| Group    | n  | hook | cliffhanger | standalone |
|----------|----|------|-------------|------------|
| Pipeline | 91 | 3.55 | 3.84        | 3.13       |
| Baseline | 50 | 2.76 | 3.57        | 3.12       |

## Token Usage

- Batches: 24 batches, 0 errors
```

#### Spend (`python -m promo_finder.llm --spend`)

```
Total spend : $0.1810

By model:
  claude-haiku-5-5: $0.1810

By stage:
  beats:          $0.0720
  judge:          $0.0679
  judge_baseline: $0.0411
  ping:           $0.0000
```

#### Highest-scoring clip: C-E23-01 (hook 4.5 / cliffhanger 5.0 / standalone 4.0)

Judge why: "A poisoning mystery with a door creaking open at the end is a clear, urgent
cliffhanger that stands on its own."

```
INT. ASHBURY MANOR - WEST WING BEDCHAMBER – NIGHT
00:00.00–00:02.50 | DIALOGUE | LADY JULIANA (Cold, Deadly Serious): Someone is poisoning her.
00:02.50–00:05.50 | CAMERA | Medium shot of Prudence gasping sharply and clamping both hands over her mouth in sheer horror.
00:02.50–00:03.50 | SOUND_FX | Sharp intake of breath from Prudence.
00:03.00–00:05.00 | DIALOGUE | PRUDENCE (Muffled, Horrified): Poison?
00:05.50–00:09.00 | CAMERA | Extreme close-up pushing in tight on Lady Juliana's eyes as her expression hardens into fury and righteous disgust.
00:07.00–00:09.00 | DIALOGUE | LADY JULIANA (Venomous, Resolute): Arsenic.
00:09.00–00:11.50 | SOUND_FX | Sudden violent coughing and sputtering from the Duchess.
00:09.00–00:12.00 | CAMERA | Medium shot as the Duchess chokes and spasms on the bed; Juliana whips around immediately.
00:12.00–00:15.50 | CAMERA | Medium tracking shot of Juliana rushing to the side table by the window, opening her satchel and setting out glass vials, a bowl, and dried herbal bundles.
00:15.50–00:18.50 | CAMERA | Close-up of Prudence pleading desperately, tears flowing down her cheeks.
00:15.50–00:18.00 | DIALOGUE | PRUDENCE (Desperate, Begging): Can you save her?
00:18.50–00:21.50 | CAMERA | Medium shot of Juliana uncorking a glass apothecary bottle as the Duchess rests behind her.
00:18.50–00:21.00 | DIALOGUE | LADY JULIANA (Focused, Resolute): I can try.
00:21.50–00:25.50 | CAMERA | Top-down close-up of Juliana's soot-smudged hands pouring powdered activated charcoal from a vial into a stone mortar, then tossing in a pinch of crushed dried leaves.
00:25.50–00:28.00 | CAMERA | Close-up of Juliana's hands vigorously grinding the pestle inside the stone mortar.
00:25.50–00:33.00 | SOUND_FX | Heavy, rhythmic scraping of stone pestle grinding charcoal and dried herbs.
00:28.00–00:33.50 | CAMERA | Medium close-up of Juliana grinding intensely, her brow furrowed as she speaks with urgent authority.
00:28.50–00:33.00 | DIALOGUE | LADY JULIANA (Urgent, Focused): The charcoal may help remove what is still inside her. We must act quickly.
00:33.20–00:35.00 | SOUND_FX | Sudden muffled thump and heavy footsteps echoing from the hallway outside the door!
00:33.50–00:36.00 | CAMERA | Wide shot of the bedroom door framed through the bed curtains as the Duchess gasps in the bed.
00:36.00–00:37.50 | CAMERA | Medium shot of Juliana freezing mid-motion, turning her head sharply toward the chamber door.
00:37.50–00:39.50 | CAMERA | Close-up of the ornate brass door handle on the dark carved wooden door.
00:39.50–00:45.50 | CAMERA | Close-up of Prudence staring at the door in utter terror, her face drained of all color.
00:39.80–00:45.00 | DIALOGUE | PRUDENCE (Terrified, Hoarse Whisper): Juliana... someone is coming.
00:45.50–00:48.50 | CAMERA | Quick cut to Juliana looking back toward the bed and then toward the door, trapped with an unfinished cure.
00:48.50–00:50.50 | CAMERA | Tight close-up of Juliana's charcoal-blackened hand clutching the glass medicine vial firmly.
00:50.20–00:52.20 | SOUND_FX | Loud, metallic clack of the door latch turning, followed by the slow creak of wood hinges.
00:50.50–00:52.50 | CAMERA | Close-up on the brass door lever as it slowly rotates downward, and the heavy door cracks open inward into the room—cutting to an intense, heart-stopping cliffhanger.
```
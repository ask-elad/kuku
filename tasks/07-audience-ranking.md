# Task 07 — Rank for the audience + unredacted review sheet

No LLM calls. Code only. Re-run ranking from the existing judge results.

## Why
A review of the top 10 found the ranking is upside-down for promos whose job is to pull in
**new** viewers: late-story payoffs (E45, E42) ranked high and spoil the endgame, while the
show's premise clip (E03) sat at #6. The "earlier episode" rule only broke ties, so it almost
never applied.

## Part A — Two audiences in `rank.py`
1. Keep `score` (0.4 hook + 0.3 cliffhanger + 0.3 standalone, sensitive −0.5) unchanged.
2. Add `acquisition_score = score − 0.5 × (first_episode − 1) / (n_episodes − 1)`
   (E01 → −0, the last episode → −0.5). Generic: it uses only the position in the series, nothing
   show-specific.
3. **Main ranking ("Post first — new viewers")**: order the main promos by `acquisition_score`
   (then the existing tie-breaks), with the same "max one per starting episode in the top 10" rule.
   `rank` follows this order.
4. **"For existing viewers (retargeting)"**: the top 5 by raw `score` among main promos whose first
   episode > 2/3 × n_episodes (rounded down), with the same one-per-episode rule. Add a field
   `audience: "retargeting"` to those; all others get `audience: "acquisition"`.
5. Keep the overlap clusters and alternatives exactly as they are.

## Part B — Outputs
- `promos.md`: section 2 becomes "Post these first: new viewers (top 10)", ordered by
  acquisition_score and showing both `score` and `acquisition_score`; add a new section
  "For existing viewers: retargeting (top 5)"; update the "Why these first" lines to explain
  the episode-position penalty and why (new viewers start at Episode 1; late payoffs spoil the
  story and need 40+ episodes of context).
- `promos.csv` / `promos.json`: add `acquisition_score` and `audience`.
- `ranking_report.md`: add the new top 10 vs the old top 10 (which promos moved in or out).

## Part C — Review sheet shows the original text
- `format_clip(promo, show, redact=True)`: the judge keeps calling it with `redact=True` (the default);
  `build/<slug>/review_top10.md` uses `redact=False`, so the editor sees the real script text.
- Regenerate the review sheet for the **new** top 10.

## Tests
- acquisition_score formula (first episode, last episode, middle)
- ranking order changes when a late promo has a higher raw score
- retargeting list: only from the last third, one per episode, max 5
- `redact=False` keeps "cliffhanger"; `redact=True` removes it

## Run
`python -m promo_finder.rank "<show>"`, then `python -m promo_finder.run "<show>"` (should
finish from cache in seconds, with no new spend).

## Definition of done
- [ ] All tests pass (report the count)
- [ ] New top-10 table + retargeting top 5 + moved in/out list pasted in Result
- [ ] Review sheet regenerated with unredacted text
- [ ] `--spend` unchanged ($0.2829)

## Result

### What was built

**Part A — `rank.py`**
- Added `_acquisition_score(score, first_episode, n_episodes)` helper: `score − 0.5 × (ep−1)/(N−1)`.
- Added `_acq_sort_key` for sorting main promos by acquisition_score (same tie-breaks: earlier episode, shorter duration, promo_id).
- `rank_promos` now derives `n_episodes = max episode number` from the show, computes `acquisition_score` on every main promo, sorts by it, then assigns retargeting audience.
- Retargeting threshold: `int(2/3 × n_episodes)`. Top-5 by raw score from last-third episodes, one-per-episode cap. Field `audience: "retargeting"` or `"acquisition"` on every ranked promo.
- Cluster resolution still uses raw `score` (unchanged).

**Part B — Outputs**
- `promos.md`: section renamed "Post these first: new viewers (top 10)" showing both `score` and `acq score` columns; new "For existing viewers: retargeting (top 5)" section; "Why these first" updated to explain the episode-position penalty.
- `promos.json` / `promos.csv`: `acquisition_score` and `audience` fields added.
- `ranking_report.md`: new "New top 10 vs old top 10" table with moved-in/moved-out summary.

**Part C — Review sheet**
- `format_clip(promo, show, redact=True)` — added `redact` parameter (default `True`, preserves existing judge behaviour).
- `_build_review_sheet` calls `format_clip(..., redact=False)` so the editor sees original script text including "cliffhanger" words.

### How to run
```
python -m promo_finder.rank "data/raw/I Married a Broken Soldier. He was a Duke"
# or the full pipeline (hits cache, no new spend):
python -m promo_finder.run "data/raw/I Married a Broken Soldier. He was a Duke"
```

### Tests
146 passed (33 in `test_rank.py` + 9 in `test_scriptfmt_redaction.py`).
New tests added:
- `test_acquisition_score_first_episode_no_penalty`
- `test_acquisition_score_last_episode_max_penalty`
- `test_acquisition_score_middle_episode`
- `test_acquisition_score_single_episode_show_no_penalty`
- `test_late_promo_higher_raw_score_loses_to_early`
- `test_retargeting_only_from_last_third`
- `test_retargeting_one_per_episode`
- `test_retargeting_max_five`
- `test_format_clip_redact_false_keeps_cliffhanger`
- `test_format_clip_redact_true_removes_cliffhanger`

### New top 10 (acquisition ranking)

| Rank | Promo | Acq score | Episodes |
|------|-------|-----------|---------|
| 1 | C-E03-01 | 4.1796 | E03 |
| 2 | C-E23-02 | 4.1255 | E23 |
| 3 | C-E26-01 | 4.0949 | E26 |
| 4 | C-E15-03 | 4.0571 | E15 |
| 5 | C-E45-01 | 3.9510 | E45 |
| 6 | C-E07-01 | 3.9388 | E07 |
| 7 | C-E11-01 | 3.8980 | E11 |
| 8 | C-E31-02 | 3.8939 | E31 |
| 9 | C-E36-02 | 3.8929 | E36 |
| 10 | C-E42-02 | 3.8316 | E42 |

### Retargeting top 5

| Rank | Promo | Score | Episodes |
|------|-------|-------|---------|
| 5 | C-E45-01 | 4.40 | E45 |
| 9 | C-E36-02 | 4.25 | E36 |
| 10 | C-E42-02 | 4.25 | E42 |
| 24 | C-E41-01 | 3.85 | E41 |
| 25 | C-E43-01 | 3.85 | E43 |

### Moved in / moved out
The same 10 promos appear in both old (score) and new (acquisition) top 10 — the existing one-per-episode variety rule already distributed across the series, so no promos were replaced. E03 jumped from #6 → #1 (premise clip, now correctly leads). E45 dropped from #1 → #5 (high raw score but episode-position penalty).

### Spend
`$0.2829` — unchanged (no new LLM calls).

### Open questions
None.
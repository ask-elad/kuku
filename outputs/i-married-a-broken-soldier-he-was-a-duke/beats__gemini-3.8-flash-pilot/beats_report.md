# Beats Report — I Married a Broken Soldier. He was a Duke

## 1. Totals

| Metric | Value |
|---|---|
| Episodes done | 3 |
| Episodes failed (LLMError) | 0 |
| Hooks kept | 13 |
| Cliffhangers kept | 10 |
| invalid_id | 0 |
| invalid_item | 0 |
| Made-up ID rate | 0.0% (0/23) |

## 2. Distributions

**Hook types:**
- humiliation: 4
- reveal: 3
- shocking_line: 3
- threat: 1
- rescue: 1
- action: 1

**Stop power distribution (hooks):**
- 5: 1
- 4: 7
- 3: 5
- 2: 0
- 1: 0

**Tension distribution (cliffhangers):**
- 5: 1
- 4: 5
- 3: 4
- 2: 0
- 1: 0

## 3. Per-episode table

| Episode | Hooks | Best stop_power | Cliffhangers | Best tension | ending_type |
|---|---|---|---|---|---|
| E01 | 5 | 5 | 4 | 4 | cliffhanger |
| E07 | 4 | 4 | 3 | 4 | resolved |
| E23 | 4 | 4 | 3 | 5 | cliffhanger |

## 4. Hooks with clean_start: null

Count: 0

## 5. Cliffhanger block types

- DIALOGUE: 5
- CAMERA: 3
- SOUND_FX: 1
- ACTION: 1

## 6. Token usage this run

| Metric | Value |
|---|---|
| Calls | 3 |
| Cached | 0 |
| Uncached | 3 |
| Prompt tokens | 14267 |
| Completion tokens | 1762 |
| Total tokens | 19485 |

## 7. Eval results

- **PASS** resolved_or_soft_endings E07: expected `ends_on_cliffhanger=false`, got `ends_on_cliffhanger=False`
- **SKIP** resolved_or_soft_endings E10: expected `ends_on_cliffhanger=false`, got `episode not in results`
- **SKIP** resolved_or_soft_endings E19: expected `ends_on_cliffhanger=false`, got `episode not in results`
- **PASS** min_top_hook_power E01: expected `best_stop_power>=4`, got `best_stop_power=5`
- **PASS** cliff_types_near_end E23: expected `type in ['CAMERA', 'SOUND_FX'], end>=02:03.50 (last 8.0s of 02:11.50)`, got `type=CAMERA, end=02:11.50`

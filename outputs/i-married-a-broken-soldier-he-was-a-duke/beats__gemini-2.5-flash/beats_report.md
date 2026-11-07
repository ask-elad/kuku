# Beats Report — I Married a Broken Soldier. He was a Duke

## 1. Totals

| Metric | Value |
|---|---|
| Episodes done | 0 |
| Episodes failed (LLMError) | 1 |
| Hooks kept | 0 |
| Cliffhangers kept | 0 |
| invalid_id | 0 |
| invalid_item | 0 |
| Made-up ID rate | 0.0% (0/0) |

Failed episodes: E19

## 2. Distributions

**Hook types:**

**Stop power distribution (hooks):**
- 5: 0
- 4: 0
- 3: 0
- 2: 0
- 1: 0

**Tension distribution (cliffhangers):**
- 5: 0
- 4: 0
- 3: 0
- 2: 0
- 1: 0

## 3. Per-episode table

| Episode | Hooks | Best stop_power | Cliffhangers | Best tension | ending_type |
|---|---|---|---|---|---|
| E19 ⚠ | 0 | 0 | 0 | 0 | ? |

## 4. Hooks with clean_start: null

Count: 0

## 5. Cliffhanger block types


## 6. Token usage this run

| Metric | Value |
|---|---|
| Calls | 0 |
| Cached | 0 |
| Uncached | 0 |
| Prompt tokens | 0 |
| Completion tokens | 0 |
| Total tokens | 0 |

## 7. Eval results

- **SKIP** resolved_or_soft_endings E07: expected `ends_on_cliffhanger=false`, got `episode not in results`
- **SKIP** resolved_or_soft_endings E10: expected `ends_on_cliffhanger=false`, got `episode not in results`
- **FAIL** resolved_or_soft_endings E19: expected `ends_on_cliffhanger=false`, got `ends_on_cliffhanger=None`
- **SKIP** min_top_hook_power E01: expected `best_stop_power>=4`, got `episode not in results`
- **SKIP** cliff_types_near_end E23: expected `type in ['CAMERA', 'SOUND_FX'], within last 8.0s`, got `episode not in results`

# Beats Report — I Married a Broken Soldier. He was a Duke

## 1. Totals

| Metric | Value |
|---|---|
| Episodes done | 50 |
| Episodes failed (LLMError) | 0 |
| Hooks kept | 201 |
| Cliffhangers kept | 88 |
| invalid_id | 0 |
| invalid_item | 0 |
| Made-up ID rate | 0.0% (0/290) |

## 2. Distributions

**Hook types:**
- shocking_line: 54
- reveal: 46
- threat: 32
- humiliation: 23
- slap_or_violence: 12
- other: 10
- action: 9
- rescue: 8
- romance: 7

**Stop power distribution (hooks):**
- 5: 30
- 4: 113
- 3: 55
- 2: 3
- 1: 0

**Tension distribution (cliffhangers):**
- 5: 19
- 4: 33
- 3: 30
- 2: 6
- 1: 0

## 3. Per-episode table

| Episode | Hooks | Best stop_power | Cliffhangers | Best tension | ending_type |
|---|---|---|---|---|---|
| E01 | 5 | 5 | 2 | 4 | cliffhanger |
| E02 | 5 | 5 | 2 | 3 | resolved |
| E03 | 5 | 5 | 1 | 5 | cliffhanger |
| E04 | 5 | 5 | 2 | 3 | soft |
| E05 | 4 | 5 | 1 | 3 | soft |
| E06 | 3 | 3 | 1 | 2 | soft |
| E07 | 4 | 4 | 2 | 3 | resolved |
| E08 | 2 | 3 | 1 | 2 | soft |
| E09 | 3 | 4 | 1 | 4 | cliffhanger |
| E10 | 4 | 4 | 2 | 3 | soft |
| E11 | 4 | 5 | 2 | 5 | cliffhanger |
| E12 | 4 | 5 | 2 | 5 | cliffhanger |
| E13 | 4 | 5 | 2 | 4 | cliffhanger |
| E14 | 4 | 4 | 1 | 4 | cliffhanger |
| E15 | 5 | 5 | 1 | 4 | cliffhanger |
| E16 | 4 | 5 | 2 | 4 | cliffhanger |
| E17 | 4 | 4 | 2 | 3 | soft |
| E18 | 5 | 5 | 2 | 5 | cliffhanger |
| E19 | 3 | 4 | 1 | 4 | soft |
| E20 | 3 | 4 | 3 | 4 | cliffhanger |
| E21 | 3 | 4 | 2 | 4 | cliffhanger |
| E22 | 3 | 4 | 1 | 5 | cliffhanger |
| E23 | 4 | 5 | 1 | 5 | cliffhanger |
| E24 | 3 | 5 | 3 | 4 | cliffhanger |
| E25 | 4 | 5 | 3 | 4 | soft |
| E26 | 3 | 4 | 2 | 5 | cliffhanger |
| E27 | 4 | 4 | 2 | 5 | cliffhanger |
| E28 | 5 | 5 | 2 | 5 | cliffhanger |
| E29 | 3 | 5 | 2 | 4 | cliffhanger |
| E30 | 4 | 4 | 2 | 5 | cliffhanger |
| E31 | 4 | 4 | 1 | 5 | cliffhanger |
| E32 | 5 | 5 | 1 | 5 | cliffhanger |
| E33 | 3 | 4 | 2 | 5 | cliffhanger |
| E34 | 5 | 4 | 3 | 5 | cliffhanger |
| E35 | 4 | 4 | 3 | 5 | cliffhanger |
| E36 | 5 | 5 | 3 | 5 | cliffhanger |
| E37 | 4 | 4 | 1 | 4 | cliffhanger |
| E38 | 3 | 4 | 1 | 5 | cliffhanger |
| E39 | 3 | 5 | 2 | 5 | cliffhanger |
| E40 | 4 | 5 | 1 | 5 | cliffhanger |
| E41 | 5 | 5 | 1 | 4 | cliffhanger |
| E42 | 5 | 4 | 1 | 4 | cliffhanger |
| E43 | 5 | 5 | 3 | 4 | cliffhanger |
| E44 | 5 | 4 | 1 | 4 | cliffhanger |
| E45 | 4 | 5 | 2 | 4 | cliffhanger |
| E46 | 5 | 5 | 2 | 4 | cliffhanger |
| E47 | 4 | 5 | 2 | 3 | resolved |
| E48 | 5 | 4 | 3 | 4 | cliffhanger |
| E49 | 4 | 4 | 1 | 3 | soft |
| E50 | 3 | 4 | 1 | 4 | cliffhanger |

## 4. Hooks with clean_start: null

Count: 0

## 5. Cliffhanger block types

- DIALOGUE: 43
- CAMERA: 31
- SOUND_FX: 9
- ACTION: 5

## 6. Token usage this run

| Metric | Value |
|---|---|
| Calls | 50 |
| Cached | 50 |
| Uncached | 0 |
| Prompt tokens | 305626 |
| Completion tokens | 82887 |
| Total tokens | 388513 |

## 7. Eval results

- **PASS** resolved_or_soft_endings E07: expected `ends_on_cliffhanger=false`, got `ends_on_cliffhanger=False`
- **PASS** resolved_or_soft_endings E10: expected `ends_on_cliffhanger=false`, got `ends_on_cliffhanger=False`
- **PASS** resolved_or_soft_endings E19: expected `ends_on_cliffhanger=false`, got `ends_on_cliffhanger=False`
- **PASS** min_top_hook_power E01: expected `best_stop_power>=4`, got `best_stop_power=5`
- **PASS** cliff_types_near_end E23: expected `type in ['CAMERA', 'SOUND_FX'], end>=02:03.50 (last 8.0s of 02:11.50)`, got `type=CAMERA, end=02:11.50`

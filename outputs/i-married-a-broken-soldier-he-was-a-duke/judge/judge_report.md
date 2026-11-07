# Judge Report

## Coverage

- 2 rounds: 91
- 1 round:  0
- 0 rounds: 0
- Batch errors: 0

## Score Distributions

- **hook**: 2→13  3→15  4→54  5→9
- **cliffhanger**: 2→8  3→10  4→60  5→13
- **standalone**: 2→14  3→45  4→32

## Judge Consistency

- Mean disagreement: 0.69
- % clips with disagreement ≥ 2: 0.0%

## Safety

- ok: 78  sensitive: 13  unsafe: 0
- Sensitive: C-E12-01, C-E12-02, C-E13-01, C-E13-02, C-E15-01, C-E16-01, C-E16-02, C-E16-03, C-E24-01, C-E24-02, C-E31-01, C-E31-02, C-E38-03

## Single vs Bridge

| Type   | n  | hook | cliffhanger | standalone |
|--------|----|------|-------------|------------|
| Single | 86 | 3.67 | 3.87        | 3.12       |
| Bridge | 5  | 3.20 | 4.20        | 2.90       |

## Baseline Comparison

| Group    | n  | hook | cliffhanger | standalone |
|----------|----|------|-------------|------------|
| Pipeline | 91 | 3.64 | 3.89        | 3.11       |
| Baseline | 50 | 2.88 | 3.56        | 3.15       |

## Token Usage

- Batches: 24 batches, 0 errors

## Calibration (Mixed Batches)

Mixed batches: 6 batches of 8 (4 pipeline + 4 baseline, seed=7)

| Group    | n  | hook | cliffhanger | standalone |
|----------|----|------|-------------|------------|
| Pipeline | 24 | 3.83 | 3.83        | 3.21       |
| Baseline | 24 | 2.58 | 2.92        | 3.12       |

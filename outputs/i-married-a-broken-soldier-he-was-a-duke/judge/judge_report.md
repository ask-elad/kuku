# Judge Report

## Coverage

- 2 rounds: 91
- 1 round:  0
- 0 rounds: 0
- Batch errors: 0

## Score Distributions

- **hook**: 1→1  2→12  3→20  4→50  5→8
- **cliffhanger**: 2→7  3→15  4→60  5→9
- **standalone**: 2→13  3→51  4→27

## Judge Consistency

- Mean disagreement: 0.66
- % clips with disagreement ≥ 2: 1.1%

## Safety

- ok: 81  sensitive: 10  unsafe: 0
- Sensitive: C-E12-01, C-E13-01, C-E13-02, C-E16-01, C-E16-02, C-E16-03, C-E24-01, C-E24-02, C-E31-01, C-E31-02

## Single vs Bridge

| Type   | n  | hook | cliffhanger | standalone |
|--------|----|------|-------------|------------|
| Single | 86 | 3.58 | 3.82        | 3.15       |
| Bridge | 5  | 3.10 | 4.10        | 2.80       |

## Baseline Comparison

| Group    | n  | hook | cliffhanger | standalone |
|----------|----|------|-------------|------------|
| Pipeline | 91 | 3.55 | 3.84        | 3.13       |
| Baseline | 50 | 2.76 | 3.57        | 3.12       |

## Token Usage

- Batches: 24 batches, 0 errors
# Ranking Report — I Married a Broken Soldier. He was a Duke

## Score Distribution (main promos)

- Count: 48
- Min: 2.30  Max: 4.40  Mean: 3.60
- Distribution: 2.3→1  2.4→1  2.6→1  2.7→1  2.8→1  2.9→2  3.1→1  3.2→2  3.3→1  3.4→5  3.5→4  3.6→2  3.7→7  3.8→2  3.9→4  4.0→4  4.2→6  4.3→2  4.4→1

## Overlap Clusters

- Total clusters: 48
- Multi-promo clusters: 24 (sizes: [5, 4, 4, 4, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2])

## Pipeline vs Baseline

### All judged promos

| Group    | n  | hook | cliffhanger | standalone | score |
|----------|----|------|-------------|------------|-------|
| Pipeline | 48 | 3.80 | 3.86        | 3.18       | 3.60  |
| Baseline | 50 | 2.88 | 3.56        | 3.15       | 3.17  |

### Top 10 of each

| Group    | n  | hook | cliffhanger | standalone | score |
|----------|----|------|-------------|------------|-------|
| Pipeline | 10 | 4.60 | 4.60        | 3.50       | 4.22  |
| Baseline | 10 | 4.10 | 4.45        | 3.65       | 4.07  |

### Mixed-batch calibration

6 batches × 8 clips (4 pipeline + 4 baseline, seed=7)

| Group    | n  | hook | cliffhanger | standalone |
|----------|----|------|-------------|------------|
| Pipeline | 24 | 3.83 | 3.83        | 3.21       |
| Baseline | 24 | 2.58 | 2.92        | 3.12       |

## Safety

- Sensitive (needs_review): 3
  C-E31-02, C-E13-02, C-E16-01
- Unsafe (excluded): 0

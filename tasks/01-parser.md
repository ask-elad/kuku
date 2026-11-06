# Task 01 — Parser: screenplay `.txt` → structured JSON

## Goal
Turn every episode file of a show into one structured JSON file, where **every timed block
has a stable ID**. All later tasks read this JSON, never the raw `.txt` files.
No LLM in this task. Pure Python, standard library (plus `pytest` for tests).

Read `docs/FINDINGS.md` first: it lists the format and the quirks.

## Input
A show folder, e.g. `"data/raw/I Married a Broken Soldier. He was a Duke"`, containing files
named like `episode-006-Episode 1671708.txt`. Shape of a file:

```
EPISODE NUMBER: Episode 1
EPISODE LOGLINE: ...
CONTINUITY NOTES: ...

--- SCRIPT START ---

SCENE 01
Scene heading: INT. CATHEDRAL – DAY
Scene start: 00:00.00
Scene end: 02:18.00

Actions and dialogue:

**CAMERA:**
Start: (00:00.00) | End: (00:04.80)
<text>

**LADY JULIANA (Confused, Breathless):**
Start: (00:13.50) | End: (00:14.30)
"Why?"

--- SCRIPT END ---
```

## Output
CLI: `python -m promo_finder.parse "<show folder>" [--out <path>]`
Default output: `build/<show-slug>/episodes.json`.

**Add `build/` to `.gitignore`.** The parsed file contains the full script text, so it is as
confidential as `data/`. (`outputs/` is only for the final promo results.)

Schema:
```json
{
  "show": {"title": "<folder name>", "slug": "<lowercase-hyphen-slug>", "n_episodes": 50},
  "episodes": [
    {
      "episode": 1,
      "source_file": "episode-001-Episode 1671703.txt",
      "logline": "...",
      "continuity_notes": "...",
      "duration": 138.0,
      "scenes": [
        {"id": "E01-S01", "number": 1, "heading": "INT. CATHEDRAL – DAY", "start": 0.0, "end": 138.0}
      ],
      "blocks": [
        {
          "id": "E01-B001",
          "episode": 1,
          "scene_id": "E01-S01",
          "type": "CAMERA | ACTION | DIALOGUE | SOUND_FX | OTHER",
          "label_raw": "LADY JULIANA (Confused, Breathless)",
          "speaker": "LADY JULIANA",
          "delivery": ["Confused", "Breathless"],
          "start": 13.5,
          "end": 14.3,
          "text": "Why?"
        }
      ]
    }
  ]
}
```

Rules:
- **IDs**: `E{ep:02d}-B{n:03d}` and `E{ep:02d}-S{n:02d}`, numbered in **file order**, starting at 1.
  The same input must always give the same IDs.
- **Types**: `CAMERA`, `ACTION`, `SOUND FX` → `SOUND_FX`; any label with a speaker name
  → `DIALOGUE`. A label you don't recognise → `OTHER` with a warning (don't drop it).
- `speaker` and `delivery` only for DIALOGUE (`null` / `[]` otherwise). Keep `speaker`
  exactly as written (upper-case, stripped). **Do not merge name aliases**
  (JULIANA vs LADY JULIANA); that is a later task.
- `text`: the block's text with surrounding whitespace removed; for DIALOGUE also remove the
  outer quote marks. Multi-line text is joined with a single space.
- Times are **float seconds** (`01:12.50` → `72.5`). Add `parse_time()` and `fmt_time()`
  helpers in `src/promo_finder/timeutil.py`; later tasks reuse them.
- `duration` = the latest end time of any scene or block in the episode.
- The episode number comes from `EPISODE NUMBER:`; cross-check it against the number in the
  filename and warn if they differ.
- **Matching must be case-insensitive** for every header (Episode 6 uses `SCENE START:`).

## Nothing may be dropped silently
Track every non-empty line of every file. Each line must be consumed as a header, scene field,
block label, timestamp or block text. Count unconsumed lines and print them in the summary
(file + line number + first 60 characters). The target is **0**.

## Summary printed at the end
- Episodes parsed, and total scenes and blocks
- Blocks per type
- Episode duration min / max / mean, and total runtime
- Warnings: unconsumed lines, end < start, block outside its scene's time range,
  episode-number mismatch, unknown labels

## Expected numbers for this show (from our own study, use them to verify)
| Check | Expected |
|---|---|
| Episodes | 50 |
| CAMERA / DIALOGUE / ACTION / SOUND_FX blocks | 1754 / 1487 / 372 / 114 |
| Episode duration | min 70.5 s, max 200.8 s, total ≈ 102.7 min |
| Blocks with end < start | 0 |
| Episode 6 | parsed with scenes and blocks (the casing trap) |

If your numbers differ, **don't adjust the code to force a match**. Report the difference in
Result and explain it; our study may be the one that's wrong.

## Tests: `tests/test_parse.py` (pytest)
Use a small handmade fixture file in `tests/fixtures/` (write 2 short fake episodes yourself,
including one with upper-case headers). **Do not copy real script text into the fixtures.**
Test:
1. `parse_time` / `fmt_time` round-trip (`"01:12.50"` ↔ `72.5`).
2. IDs are unique and sequential; scene_id references an existing scene.
3. Upper-case headers parse the same as normal ones.
4. Dialogue: speaker, delivery and quote-stripping are correct.
5. Unknown label → type OTHER plus a warning, not a crash.
6. Unconsumed-line count is 0 for the fixtures.

Add `pytest` (pinned) to `requirements.txt`.

## Out of scope (don't do these)
- Merging character name aliases
- Dropping or summarising CAMERA blocks
- Any LLM call, prompts, or promo logic

## Definition of done
- [ ] `python -m promo_finder.parse "data/raw/<show>"` writes `build/<slug>/episodes.json`
- [ ] Summary shows 0 unconsumed lines, or each remaining one is explained in Result
- [ ] Numbers match the table above, or the difference is explained
- [ ] `pytest` passes
- [ ] `build/` is in `.gitignore`; `git status` shows no data or build files

## Result

### What was built
- `src/promo_finder/timeutil.py` — `parse_time()` and `fmt_time()` helpers
- `src/promo_finder/parse.py` — CLI entry point + `parse_episode()` / `parse_show()` / `parse_label()`
- `tests/test_parse.py` — 15 tests covering all 6 required cases
- `tests/fixtures/ep_normal.txt` / `ep_upper.txt` — handmade fictional fixtures
- `requirements.txt` — `pytest==8.3.4`
- `conftest.py` — adds `src/` to sys.path for pytest
- `.gitignore` updated with `build/`

### How to run
```
# Parse the show (creates build/<slug>/episodes.json)
PYTHONPATH=src python -m promo_finder.parse "data/raw/I Married a Broken Soldier. He was a Duke"

# Or with venv
.venv/bin/python -m promo_finder.parse "data/raw/I Married a Broken Soldier. He was a Duke"

# Tests
.venv/bin/python -m pytest tests/test_parse.py -v
```

### Actual summary numbers
| Check | Expected | Actual |
|---|---|---|
| Episodes | 50 | 50 ✓ |
| CAMERA blocks | 1754 | 1754 ✓ |
| DIALOGUE blocks | 1487 | 1487 ✓ |
| ACTION blocks | 372 | 372 ✓ |
| SOUND_FX blocks | 114 | 114 ✓ |
| Min duration | 70.5 s | 70.5 s ✓ |
| Max duration | 200.8 s | 200.75 s (see below) |
| Total runtime | ≈102.7 min | 102:42.62 ≈ 102.71 min ✓ |
| end < start blocks | 0 | 0 ✓ |
| Unconsumed lines | 0 | 0 ✓ |
| Episode 6 (casing) | scenes + blocks | 2 scenes, 97 blocks ✓ |

### Max-duration discrepancy
Expected 200.8 s; actual Episode 36 scene end is `03:20.75` (200.75 s) in the source file. The 0.05 s difference is in the original study's number; the parser faithfully reflects the file.

### New data quirks found
1. **Episode 22, block E22-B023 (SOUND FX "Heavy wooden latch clicks shut…")**: end time is 42.80 s but the scene is declared to end at 42.50 s — a 0.30 s overrun. The sound continues fractionally past the scene cut. This is the only "block outside scene range" warning across all 50 episodes.

### Open questions
- None for this task.
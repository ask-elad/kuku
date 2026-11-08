# Kuku Promo Finder

Reads the screenplays of a microdrama series (one `.txt` per episode) and finds the best
20–60 s clips for Instagram / TikTok / YouTube. Each promo opens on a hook that stops a
scrolling viewer, ends on a cliffhanger, and makes sense to someone who has never seen the show.

Final outputs: `outputs/<show-slug>/final/promos.md` / `promos.csv` / `promos.json`

## Setup

Requires Python 3.12.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # then add your API key
```

## Input

Put the show folder in `data/raw/<show>/`, one `.txt` per episode.
The input pack is not in the repo (confidential).

## Run

```bash
python -m promo_finder.run "data/raw/<show folder>"
```

Options:
- `--no-baseline` — skip the baseline comparison step to save cost on a new show

A full run on a 50-episode show takes about 15–20 minutes and costs **~$0.25** on
Claude Haiku 5.5 (including the baseline comparison). LLM calls are cached, so a
re-run completes in **under 10 seconds** at no extra cost.

## Switching models

Edit `.env`:

```
# Primary (Claude):
LLM_MODEL=claude-haiku-5-5
# LLM_MODEL_JUDGE=claude-sonnet-5-5   ← stronger judge; costs more

# Fallback (Gemini) — comment the Claude block and uncomment:
# LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
# LLM_MODEL=gemini-3.8-flash
# Note: new Google accounts cannot use gemini-2.5-flash; use gemini-3.8-flash instead.
```

## Pipeline overview

| Stage | Module | What it does |
|-------|--------|--------------|
| parse | `promo_finder.parse` | Parses `.txt` scripts into `build/<slug>/episodes.json` |
| baseline | `promo_finder.baseline` | Builds simple last-45 s baselines for comparison |
| beats | `promo_finder.beats` | Finds hook + cliffhanger beat pairs via LLM |
| candidates | `promo_finder.candidates` | Assembles valid 20–60 s promo clips from beats |
| judge | `promo_finder.judge` | LLM cold-viewer scores each clip (hook / cliffhanger / standalone) |
| rank | `promo_finder.rank` | Scores, clusters overlaps, picks top 10 with episode variety |

Prompts live in `prompts/`.

Design decisions: [docs/DECISIONS.md](docs/DECISIONS.md)
Data findings: [docs/FINDINGS.md](docs/FINDINGS.md)

## Tests

```bash
pytest
```

# CLAUDE.md — Kuku Promo Finder

## What we are building
A command-line tool that reads the screenplays of a microdrama series (one `.txt` per
episode, every block timestamped) and finds the best **promos**: 20–60 s clips for
Instagram / TikTok / YouTube that pull in new viewers. A promo is one continuous segment,
or a few segments joined (from one or several episodes). A good promo:
1. **opens on a hook**: something in the first 3 s that stops a scrolling viewer;
2. **ends on a cliffhanger**: it cuts at an unresolved moment;
3. **makes sense on its own** to someone who has never seen the show.

For every promo the tool outputs: the segments in order (episode, start, end), the hook,
the cliffhanger, one line on why it works, and a rank. The user is a promo editor at Kuku
who today watches every episode by hand.

## How we work (read this first, every session)
- The human and a separate planning assistant make the design decisions. **You implement.**
- Work **only** on the task file you are given (`tasks/NN-*.md`). Do not start the next
  task, refactor unrelated code, or "improve" the design on your own.
- If something in the task is ambiguous or you think a decision is needed: **stop and ask**.
  Do not pick silently.
- When you finish, fill in the task file's `## Result` section: what you built, how to run
  it, what you checked, anything surprising in the data, and open questions.
- If you find a new data quirk, add it to the `## Result` section; the human will move it
  into `docs/FINDINGS.md`.

## Hard rules: never break these
1. **Never commit, print in bulk, or copy the input pack.** `data/` is confidential and gitignored.
   Never edit files in `data/raw/`.
2. **The LLM never writes timestamps.** Code gives every script block an ID; the LLM only
   returns IDs; code converts IDs to timestamps. Every timestamp in an output must exist in
   the source script.
3. **All model calls go through one module** (`src/promo_finder/llm.py`, built in a later task).
   No direct SDK calls anywhere else. The model must be swappable via config/env.
4. **Prompts live in `prompts/`** as text files, never as long strings inside Python.
5. **Secrets come from `.env`.** Never hard-code or print API keys.
6. **Raw outputs are never hand-edited.** `outputs/` holds exactly what the tool produced.

- **One run at a time.** Run LLM jobs in the foreground and wait for them. Never start a second run of anything while one is still going; check for running processes first. If a command goes to the background on its own, wait for it, and don't launch it again.

## Repo map
| Path | Purpose |
|---|---|
| `data/raw/<show>/` | Input pack, one folder per show (gitignored). Folder names may contain spaces and dots |
| `src/promo_finder/` | All code, as a Python package |
| `prompts/` | Prompt templates |
| `tests/` | Checks of the hard rules (duration, timestamps exist, ordering) |
| `outputs/<show-slug>/` | Raw outputs (committed; a required deliverable) |
| `cache/` | Cached LLM responses (gitignored) |
| `tasks/` | One file per task |
| `docs/FINDINGS.md` | Data quirks: **read before touching the parser** |
| `docs/DECISIONS.md` | Why the design is the way it is: read before proposing changes |

## Code style
- Python 3.12, standard library first. Add a dependency only if the task allows it, and
  add it to `requirements.txt` with a pinned version.
- Small, plain functions, type hints, no classes unless they clearly help.
- Every entry point runs from the command line and takes the **show folder path as an
  argument**, e.g. `python -m promo_finder.parse "data/raw/<show>"`. No hard-coded show names.
  Always quote paths.
- Times are handled internally as **float seconds**; format as `MM:SS.ss` only for output.
- Be deterministic where possible: sort inputs, stable IDs, and set temperature/seed where the
  model allows it.
- Keep explanations in your replies short. Put details in the task's `## Result` section.
# Task 03b — Make the LLM layer work with Claude (Gemini stays as a fallback)

## Why
We are moving from the Gemini free tier (20 requests/day) to the Claude API, through Anthropic's
**OpenAI SDK compatibility endpoint** (`https://api.anthropic.com/v1/`), so we keep the
`openai` package and all of `llm.py`'s design. Gemini must keep working by changing `.env` only.

Facts from Anthropic's docs that force code changes:
1. `response_format: {"type": "json_object"}` returns **HTTP 400** (only `json_schema` with
   `strict: true` is accepted). Our prompts already demand JSON only, plus fence stripping and
   one repair retry, so we simply **don't send** `response_format` for Claude.
2. `temperature`: on Claude 4.7+ models, **any value below 1 returns HTTP 400**, so it must be
   **omitted**. Our default of 0.0 would break every call.
3. Claude 5 models think by default; the thinking isn't returned but is billed as output.
   Keep `LLM_MAX_TOKENS` high enough (16000 is fine).
4. Personal keys not scoped to a workspace need an `anthropic-workspace-id` header.
5. Prices (USD per million tokens, prompts ≤ 100k tokens): Haiku 5.5 $0.10 in / $0.50 out;
   Sonnet 5.5 $2 in / $10 out. The credit balance is small (~$8), so we track spend and cap it.

## Changes to `src/promo_finder/llm.py`

### 1. New config (env / `.env`)
| Variable | Default | Meaning |
|---|---|---|
| `LLM_TEMPERATURE` | `0` | A number, or `omit` = don't send temperature at all |
| `LLM_JSON_MODE` | `json_object` | `json_object` = send `response_format`; `off` = don't send it |
| `LLM_MODEL_<STAGE>` | unset | Per-stage model override. Stage = the part of `tag` before the first `:` (`beats:E07` → `LLM_MODEL_BEATS`, `judge:r1:b03` → `LLM_MODEL_JUDGE`). Falls back to `LLM_MODEL` |
| `LLM_EXTRA_HEADERS` | unset | Optional JSON object of extra HTTP headers, passed as `default_headers` to the client (e.g. `{"anthropic-workspace-id": "..."}`) |
| `LLM_BUDGET_USD` | unset (no cap) | Stop before any uncached call once the logged spend reaches this |

- `complete_json` / `complete_text`: change `temperature` to default `None` = use `LLM_TEMPERATURE`.
  An explicit argument still wins.
- **Cache key**: use the *effective* values: the resolved model (after the stage override), the
  temperature (number or the string `"omit"`) and the JSON mode. Gemini answers stay in the cache and
  never collide with Claude's.
- Keep the existing "400 mentioning response_format → retry without" fallback as a safety net.

### 2. Cost tracking: `prices.json` (repo root, committed)
```json
{
  "_note": "USD per 1M tokens. Claude Haiku 5.5 rate is for prompts <= 100k tokens.",
  "claude-haiku-5-5":  {"in": 0.10, "out": 0.50},
  "claude-sonnet-5-5": {"in": 2.00, "out": 10.00},
  "gemini-2.5-flash":  {"in": 0.00, "out": 0.00},
  "gemini-3.8-flash":  {"in": 0.00, "out": 0.00}
}
```
- Add a `cost_usd` column to `logs/llm_usage.csv`: `prompt_tokens * in + completion_tokens * out`,
  divided by 1e6. **Cached calls cost 0** (the row still logs their tokens with `cached=true`).
  Unknown model → cost blank, plus a one-time warning.
- The old CSV has no `cost_usd` column: if the header differs, rename the old file to
  `logs/llm_usage.old.csv` and start a new one.
- **Budget guard**: before every **uncached** call, sum `cost_usd` over the CSV; if it's
  ≥ `LLM_BUDGET_USD`, raise `LLMBudgetExceeded(LLMError)`. `beats.py` treats it like
  `LLMQuotaExhausted`: stop the run, write the report, list the remaining episodes.
- Add `python -m promo_finder.llm --spend` → prints the total spend, broken down by model and by stage.

### 3. `--ping`
Prints: base URL host, the resolved model for stage `ping`, temperature mode, JSON mode, and
whether extra headers are set (never print header values or the key). After the call, prints
tokens and `cost_usd`.

## `.env.example` (replace)
```dotenv
# ---------- Primary: Claude (OpenAI-compatible endpoint) ----------
LLM_BASE_URL=https://api.anthropic.com/v1/
LLM_API_KEY=
LLM_MODEL=claude-haiku-5-5
# LLM_MODEL_JUDGE=claude-sonnet-5-5     # optional: stronger judge
LLM_TEMPERATURE=omit
LLM_JSON_MODE=off
LLM_MIN_INTERVAL_S=1.5
LLM_MAX_TOKENS=16000
LLM_BUDGET_USD=6.00
# LLM_EXTRA_HEADERS={"anthropic-workspace-id":"wrkspc_..."}

# ---------- Fallback: Gemini (comment the block above, uncomment this) ----------
# LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
# LLM_API_KEY=
# LLM_MODEL=gemini-3.8-flash
# LLM_TEMPERATURE=0
# LLM_JSON_MODE=json_object
# LLM_MIN_INTERVAL_S=13
```

## Tests: extend `tests/test_llm.py` (fake client, no network)
1. `LLM_TEMPERATURE=omit` → no `temperature` in the request; a number → sent.
2. `LLM_JSON_MODE=off` → no `response_format` in the request.
3. Stage override: `LLM_MODEL_JUDGE` is used for tag `judge:r1:b01`; `LLM_MODEL` for `beats:E01`.
4. The cache key differs when the model, the temperature mode or the JSON mode differs.
5. `LLM_EXTRA_HEADERS` → passed to the client; invalid JSON → a clear error.
6. `cost_usd`: correct for a known model; 0 for a cached call; blank for an unknown model.
7. The budget guard raises before the call when the spend in the CSV ≥ the budget; cached calls still work when over budget.
8. `beats.py` stops cleanly on `LLMBudgetExceeded`.

## Housekeeping
- Stop any running beats process first (CLAUDE.md: one run at a time).
- `outputs/<slug>/beats__gemini-2.5-flash/` stays as is (the archive).
- If `outputs/<slug>/beats/` currently holds Gemini 3.8 pilot results, move it to
  `outputs/<slug>/beats__gemini-3.8-flash-pilot/`. Otherwise delete it (it gets regenerated).

## How to run (in this order)
1. Tests pass.
2. `python -m promo_finder.llm --ping` against Claude. If it fails with an auth or workspace
   error, **stop and report the exact message** (without the key).
3. **Beats pilot on Claude**: `python -m promo_finder.beats "<show>" --episodes 1,7,23`, in the
   foreground. Report the same metrics as the earlier pilot, **plus the cost from `--spend`**. Then STOP.

## Out of scope
- Native Anthropic SDK, `json_schema` structured outputs, prompt caching (possible future work)
- Any prompt changes

## Definition of done
- [ ] Tests pass; the ping works on Claude
- [ ] Claude pilot report + spend in Result
- [ ] `git status`: `prices.json` and `.env.example` updated; no `.env`, `cache/` or `logs/`

## Result

### What was built

- `llm.py`: added `LLM_TEMPERATURE` ("omit" or float), `LLM_JSON_MODE` ("json_object"/"off"), `LLM_MODEL_<STAGE>` per-stage overrides, `LLM_EXTRA_HEADERS` JSON object for `default_headers`, `LLM_BUDGET_USD` cap with `LLMBudgetExceeded` guard. `_cache_key` now uses effective model, temperature (or "omit"), and JSON mode string — Gemini entries stay in cache without collision. `cost_usd` column added to CSV; old CSV auto-renamed to `.old.csv`. `--spend` subcommand added. `--ping` updated to show temperature/JSON/headers config.
- `beats.py`: catches `LLMBudgetExceeded` exactly like `LLMQuotaExhausted` — stops run, writes report, lists remaining episodes.
- `prices.json`: created at repo root.
- `.env.example`: replaced with Claude-primary / Gemini-fallback blocks.
- `outputs/<slug>/beats/`: moved to `beats__gemini-3.8-flash-pilot/` (held gemini-3.8-flash results).

### How to run

```
# Tests
python -m pytest tests/test_llm.py -v

# Ping (from repo root)
PYTHONPATH=src python -m promo_finder.llm --ping

# Beats pilot
PYTHONPATH=src python -m promo_finder.beats "data/raw/I Married a Broken Soldier. He was a Duke" --episodes 1,7,23

# Spend report
PYTHONPATH=src python -m promo_finder.llm --spend
```

### Claude pilot results (claude-haiku-5-5, episodes 1, 7, 23)

| Metric | Value |
|---|---|
| Episodes done | 3 / 3 |
| Hooks kept | 13 |
| Cliffhangers kept | 5 |
| Made-up ID rate | 0.0% (0/18) |
| Total tokens | 22 241 |
| Uncached calls | 3 |
| Latency | ~2–3 s/ep |
| **Total spend** | **$0.0039** |

Eval: 3 PASS, 2 SKIP (episodes not in pilot). Zero invalid IDs — Claude follows the block-ID schema perfectly.

### Spend from `--spend`

```
Total spend : $0.0039
By model:
  claude-haiku-5-5: $0.0039
By stage:
  beats: $0.0039
  ping: $0.0000
```

### Surprising observations

- Claude produces fewer cliffhangers than Gemini on the same episodes (5 vs ~8), but all were valid block IDs. May reflect tighter quality threshold rather than a failure.
- Latency ~2–3 s/episode — much faster than gemini-3.8-flash (which hit 15–16 min/episode in the previous pilot).
- Token counts (22k total for 3 eps) are consistent with the gemini-2.5-flash pilot.

### Open questions

- Cliffhanger count is lower than Gemini pilots — intentional or model conservatism? Worth watching on a full run.
- Budget guard is set to $6.00; a full 23-episode run at this rate would cost ~$0.03. The cap is generous; may want to tighten it once cost/episode is better characterised.
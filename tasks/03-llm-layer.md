# Task 03 — Swappable LLM layer

## Goal
Build `src/promo_finder/llm.py`: the **only** place in the codebase that talks to a model.
Switching models (Gemini → Groq → OpenRouter → local Ollama → whatever API Kuku gives us)
must need **only `.env` changes, no code changes**. No promo logic in this task.

## Config (environment / `.env`)
| Variable | Default | Meaning |
|---|---|---|
| `LLM_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` | Any OpenAI-compatible endpoint |
| `LLM_API_KEY` | falls back to `GEMINI_API_KEY` if unset | API key |
| `LLM_MODEL` | `gemini-2.5-flash` | Model name |
| `LLM_MIN_INTERVAL_S` | `6.5` | Minimum seconds between **uncached** calls (free tier ≈ 10 req/min) |
| `LLM_MAX_TOKENS` | `16000` | Output cap (Gemini 2.5 "thinking" tokens count against it) |
| `LLM_CACHE` | `1` | `0` disables the cache |

Update `.env.example` with all of these, with **empty key values**. Never print the key.
Real environment variables override `.env`.

## Dependencies
Add `openai` and `python-dotenv` to `requirements.txt`, pinned to the current versions you install.

## Public interface (keep it this small)
```python
def complete_json(prompt_name: str, variables: dict, *, tag: str,
                  temperature: float = 0.0) -> dict
def complete_text(prompt_name: str, variables: dict, *, tag: str,
                  temperature: float = 0.0) -> str
```
- `prompt_name` → loads `prompts/<prompt_name>.md`.
- **Templating**: replace `{{name}}` placeholders with `variables[name]`. Use double braces so
  JSON examples inside prompts (`{ ... }`) are left alone. A placeholder without a value →
  raise an error naming it. A variable that isn't used → also an error (catches typos).
- A prompt file may contain a line `---USER---`. Text above it is the system message, text
  below is the user message. If the line is missing, everything is the user message.
- `tag` is a short label for logs (e.g. `beats:E07`).

## Behaviour
1. **Cache**: key = sha256 of the canonical JSON of `{model, messages, temperature,
   max_tokens, json_mode}`. The base URL and key are **not** in it, but the model name is,
   so a new model never reuses an old model's answers. Store `cache/llm/<key>.json`
   containing the request, the raw response text, usage, and model. On a cache hit, return
   immediately with no rate-limit wait.
2. **JSON mode**: send `response_format={"type": "json_object"}`. If the provider rejects
   that parameter (HTTP 400 mentioning response_format), resend without it, remember that
   choice for the rest of the process, and continue.
3. **JSON parsing**: strip ```` ```json ```` fences, parse, and check the result is a JSON object.
   If parsing fails: **one** repair retry, sending the bad output plus the parse error and
   asking for valid JSON only. If that fails too, raise `LLMError` with the tag and the
   first 300 characters of the output. Never silently return `{}`.
4. **Truncation**: if `finish_reason == "length"`, raise `LLMError` (never parse half an
   answer); the message suggests raising `LLM_MAX_TOKENS`.
5. **Retries**: on HTTP 429, 5xx, timeouts and connection errors, wait 5, 10, 20, 40, 80 s
   (or honour `Retry-After` if it's longer), then give up with a clear `LLMError`. Don't retry
   other 4xx errors (bad key, bad model name); fail immediately with a readable message.
6. **Rate limit**: keep at least `LLM_MIN_INTERVAL_S` seconds between uncached calls.
7. **Usage log**: append one row per call (cached or not) to `logs/llm_usage.csv`:
   `time, tag, model, cached, prompt_tokens, completion_tokens, total_tokens, latency_s`.
   For a cached call, log the tokens stored in the cache with `cached=true`. Add `logs/` to
   `.gitignore`.
8. Build the OpenAI client in one small function (`_client()`), so tests can replace it.

## Smoke test CLI
`python -m promo_finder.llm --ping`
- Prints the base URL host and the model name (never the key).
- Calls `complete_json("ping", {"word": "promo"}, tag="ping")` using a new `prompts/ping.md`
  that asks for `{"ok": true, "echo": "<word>"}`.
- Prints the parsed result, tokens and latency; then calls it again and shows it was a cache hit.

`python -m promo_finder.llm --list-models` → prints the model names the endpoint offers (if
the endpoint supports listing; otherwise a clear message).

## Tests: `tests/test_llm.py` (no network; replace `_client()` with a fake)
1. Templating: fills values; a missing variable raises; an unused variable raises; JSON braces in
   the prompt survive.
2. The system/user split on `---USER---` works.
3. The second identical call is served from cache (the fake client is called once).
4. A different model name → cache miss.
5. A fenced ```` ```json ```` reply is parsed.
6. Invalid JSON → one repair call → success; invalid twice → `LLMError`.
7. `finish_reason == "length"` → `LLMError`.
8. A 429 then success → retried (patch the sleep so tests are fast); a 401 → no retry.
9. `response_format` rejected → retried without it.
10. Usage CSV gets a row per call.

## Out of scope
- Any promo logic or real prompts besides `ping.md`
- Async / parallel calls
- Provider-specific SDKs (only the `openai` package)

## Definition of done
- [ ] `python -m promo_finder.llm --ping` works against Gemini with the key from `.env`
- [ ] The second ping is a cache hit (shown in the output and in `logs/llm_usage.csv`)
- [ ] `--list-models` runs (paste the Gemini flash models it shows into Result)
- [ ] All tests pass (old and new), with no network calls in the tests
- [ ] `git status` shows no `cache/`, `logs/` or `.env`

## Result

### Files built
| File | Purpose |
|---|---|
| `src/promo_finder/llm.py` | LLM gateway: `complete_json`, `complete_text`, CLI `--ping` / `--list-models` |
| `prompts/ping.md` | Minimal ping prompt |
| `tests/test_llm.py` | 15 unit tests (no network) |
| `.env.example` | Updated with all 7 LLM_* vars |
| `.gitignore` | Added `logs/` |
| `requirements.txt` | Added `openai==3.46.0`, `python-dotenv==1.2.4` |

### Ping output (key hidden)
```
Endpoint : generativelanguage.googleapis.com
Model    : gemini-2.5-flash

Result   : {'ok': True, 'echo': 'promo'}
Tokens   : prompt=31 completion=18 total=83
Latency  : 1.95s
Cached   : false

Result   : {'ok': True, 'echo': 'promo'}
Latency  : 0.0005s
Cached   : true  ← should be true
```

### Available flash models (from --list-models)
```
models/gemini-2.5-flash
models/gemini-2.5-flash-image
models/gemini-2.5-flash-lite
models/gemini-2.5-flash-native-audio-latest
models/gemini-2.5-flash-native-audio-preview-09-2025
models/gemini-2.5-flash-native-audio-preview-12-2025
models/gemini-2.5-flash-preview-tts
models/gemini-3-flash-preview
models/gemini-3.1-flash-image
models/gemini-3.1-flash-image-preview
models/gemini-3.1-flash-lite
models/gemini-3.1-flash-lite-image
models/gemini-3.1-flash-lite-preview
models/gemini-3.1-flash-live-preview
models/gemini-3.1-flash-tts-preview
models/gemini-3.5-flash
models/gemini-3.5-flash-lite
models/gemini-3.6-flash
models/gemini-3.7-flash
models/gemini-3.8-flash
models/gemini-3.8-flash-lite-tts
models/gemini-3.8-flash-tts
models/gemini-flash-latest
models/gemini-flash-lite-latest
```
(full list of all models is longer — only flash models shown here)

### Notes
- Gemini **accepted** `response_format={"type": "json_object"}` — the fallback path was not triggered.
- The `openai` package installed is v3.46.0 (the package's version numbering has gone past 1.x); it supports the same `OpenAI(base_url=...)` / `client.chat.completions.create()` API as 1.x.
- `PYTHONPATH=src python -m promo_finder.llm --ping` is required unless the package is installed; the entry point follows the same pattern as `parse.py`.
- All 45 tests pass (15 new + 30 existing), zero network calls in tests.
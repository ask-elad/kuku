"""Single LLM gateway — all model calls go through here."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import openai
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

_BASE_URL: str = os.environ.get("LLM_BASE_URL", _DEFAULT_BASE_URL)
_API_KEY: str = os.environ.get("LLM_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
_MODEL: str = os.environ.get("LLM_MODEL", "gemini-2.5-flash")
_MIN_INTERVAL: float = float(os.environ.get("LLM_MIN_INTERVAL_S", "6.5"))
_MAX_TOKENS: int = int(os.environ.get("LLM_MAX_TOKENS", "16000"))
_CACHE_ENABLED: bool = os.environ.get("LLM_CACHE", "1") != "0"

_TEMPERATURE_STR: str = os.environ.get("LLM_TEMPERATURE", "0")
_TEMPERATURE: float | str = (
    "omit" if _TEMPERATURE_STR.lower() == "omit" else float(_TEMPERATURE_STR)
)

_JSON_MODE: str = os.environ.get("LLM_JSON_MODE", "json_object")  # "json_object" or "off"

_EXTRA_HEADERS_STR: str | None = os.environ.get("LLM_EXTRA_HEADERS")

_budget_str = os.environ.get("LLM_BUDGET_USD")
_BUDGET_USD: float | None = float(_budget_str) if _budget_str else None

_REPO_ROOT = Path(__file__).parent.parent.parent
_PROMPTS_DIR = _REPO_ROOT / "prompts"
_CACHE_DIR = _REPO_ROOT / "cache" / "llm"
_LOG_PATH = _REPO_ROOT / "logs" / "llm_usage.csv"
_PRICES_PATH = _REPO_ROOT / "prices.json"

# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------
def _load_prices() -> dict:
    if _PRICES_PATH.exists():
        return json.loads(_PRICES_PATH.read_text(encoding="utf-8"))
    return {}


_PRICES: dict = _load_prices()
_unknown_model_warned: set[str] = set()


def _compute_cost(model: str, cached: bool, prompt_tokens: int,
                  completion_tokens: int) -> str:
    """Return cost as a 6-decimal string, '' for unknown models, '0.000000' for cached."""
    if cached:
        return "0.000000"
    prices = _PRICES.get(model)
    if prices is None:
        if model not in _unknown_model_warned:
            _unknown_model_warned.add(model)
            import sys
            print(
                f"Warning: no price data for model {model!r}; cost_usd will be blank",
                file=sys.stderr,
            )
        return ""
    cost = (prompt_tokens * prices["in"] + completion_tokens * prices["out"]) / 1e6
    return f"{cost:.6f}"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_last_call_time: float = 0.0
_json_mode_rejected: bool = False
_csv_header_checked: bool = False

_CSV_HEADER = [
    "time", "tag", "model", "cached",
    "prompt_tokens", "completion_tokens", "total_tokens", "latency_s", "cost_usd",
]


class LLMError(RuntimeError):
    pass


class LLMQuotaExhausted(LLMError):
    """Raised when the daily API quota is exhausted. No point retrying."""
    pass


class LLMBudgetExceeded(LLMError):
    """Raised when the configured spend budget is reached."""
    pass


# ---------------------------------------------------------------------------
# Client factory (replaceable in tests)
# ---------------------------------------------------------------------------
def _client() -> openai.OpenAI:
    kwargs: dict[str, Any] = {"base_url": _BASE_URL, "api_key": _API_KEY}
    if _EXTRA_HEADERS_STR:
        try:
            kwargs["default_headers"] = json.loads(_EXTRA_HEADERS_STR)
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM_EXTRA_HEADERS is not valid JSON: {exc}") from exc
    return openai.OpenAI(**kwargs)


# ---------------------------------------------------------------------------
# Prompt loading + templating
# ---------------------------------------------------------------------------
def _load_prompt(prompt_name: str, variables: dict[str, str]) -> tuple[str | None, str]:
    """Return (system_message, user_message) with {{placeholders}} filled."""
    path = _PROMPTS_DIR / f"{prompt_name}.md"
    if not path.exists():
        raise LLMError(f"Prompt file not found: {path}")
    text = path.read_text(encoding="utf-8")

    used: set[str] = set()

    def replacer(m: re.Match) -> str:
        name = m.group(1)
        if name not in variables:
            raise LLMError(
                f"Prompt '{prompt_name}' uses placeholder '{{{{{name}}}}}' but it was not supplied"
            )
        used.add(name)
        return str(variables[name])

    filled = re.sub(r"\{\{(\w+)\}\}", replacer, text)

    unused = set(variables) - used
    if unused:
        raise LLMError(
            f"Prompt '{prompt_name}': variables supplied but not used: {sorted(unused)}"
        )

    if "---USER---" in filled:
        system_part, user_part = filled.split("---USER---", 1)
        return system_part.strip(), user_part.strip()
    return None, filled.strip()


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def _cache_key(model: str, messages: list[dict], temperature: float | str,
               max_tokens: int, json_mode: str) -> str:
    payload = json.dumps(
        {"model": model, "messages": messages, "temperature": temperature,
         "max_tokens": max_tokens, "json_mode": json_mode},
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _cache_load(key: str) -> dict | None:
    if not _CACHE_ENABLED:
        return None
    path = _CACHE_DIR / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _cache_save(key: str, entry: dict) -> None:
    if not _CACHE_ENABLED:
        return
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (_CACHE_DIR / f"{key}.json").write_text(
        json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Usage log
# ---------------------------------------------------------------------------
def _migrate_log_if_needed() -> None:
    """If existing CSV has outdated headers, rename to .old.csv and start fresh."""
    if not _LOG_PATH.exists():
        return
    with _LOG_PATH.open(encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return
    if header != _CSV_HEADER:
        old_path = _LOG_PATH.with_suffix(".old.csv")
        _LOG_PATH.rename(old_path)


def _log_usage(tag: str, model: str, cached: bool, prompt_tokens: int,
               completion_tokens: int, total_tokens: int, latency_s: float) -> None:
    global _csv_header_checked
    if not _csv_header_checked:
        _csv_header_checked = True
        _migrate_log_if_needed()

    cost_usd = _compute_cost(model, cached, prompt_tokens, completion_tokens)

    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not _LOG_PATH.exists()
    with _LOG_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(_CSV_HEADER)
        writer.writerow([
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            tag, model, str(cached).lower(),
            prompt_tokens, completion_tokens, total_tokens,
            f"{latency_s:.3f}",
            cost_usd,
        ])


# ---------------------------------------------------------------------------
# JSON fence stripping + parsing
# ---------------------------------------------------------------------------
def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _parse_json_object(text: str) -> dict:
    cleaned = _strip_fences(text)
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(result, dict):
        raise ValueError(f"Expected a JSON object, got {type(result).__name__}")
    return result


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
def _wait_for_rate_limit() -> None:
    global _last_call_time
    elapsed = time.monotonic() - _last_call_time
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_call_time = time.monotonic()


# ---------------------------------------------------------------------------
# Budget guard
# ---------------------------------------------------------------------------
def _check_budget() -> None:
    if _BUDGET_USD is None:
        return
    if not _LOG_PATH.exists():
        return
    total = 0.0
    with _LOG_PATH.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cost_str = row.get("cost_usd", "")
            if cost_str:
                try:
                    total += float(cost_str)
                except ValueError:
                    pass
    if total >= _BUDGET_USD:
        raise LLMBudgetExceeded(
            f"Budget cap: ${total:.4f} spent >= ${_BUDGET_USD:.2f} limit"
        )


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------
def _resolve_model(tag: str) -> str:
    """Return per-stage env override (LLM_MODEL_<STAGE>), else _MODEL."""
    stage = tag.split(":")[0].upper()
    return os.environ.get(f"LLM_MODEL_{stage}", _MODEL)


# ---------------------------------------------------------------------------
# Core call with retry
# ---------------------------------------------------------------------------
_RETRY_DELAYS = [5, 10, 20, 40, 80]


def _call_api(client: openai.OpenAI, model: str, messages: list[dict],
              temperature: float | str, max_tokens: int,
              use_json_mode: bool) -> tuple[str, str, dict]:
    """Return (content, finish_reason, usage_dict). May raise LLMError."""
    global _json_mode_rejected

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if temperature != "omit":
        kwargs["temperature"] = temperature
    if use_json_mode and not _json_mode_rejected:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt, delay in enumerate([-1] + _RETRY_DELAYS):
        if attempt > 0:
            time.sleep(delay)
        try:
            resp = client.chat.completions.create(**kwargs)
            choice = resp.choices[0]
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
                "total_tokens": resp.usage.total_tokens if resp.usage else 0,
            }
            return choice.message.content or "", choice.finish_reason, usage

        except openai.BadRequestError as exc:
            body = str(exc).lower()
            if use_json_mode and not _json_mode_rejected and "response_format" in body:
                _json_mode_rejected = True
                kwargs.pop("response_format", None)
                continue
            raise LLMError(f"Bad request: {exc}") from exc

        except openai.AuthenticationError as exc:
            raise LLMError(f"Authentication failed (check API key): {exc}") from exc

        except openai.PermissionDeniedError as exc:
            raise LLMError(f"Permission denied: {exc}") from exc

        except openai.NotFoundError as exc:
            raise LLMError(f"Model or endpoint not found: {exc}") from exc

        except openai.RateLimitError as exc:
            if _is_daily_quota(exc):
                raise LLMQuotaExhausted(
                    f"Daily quota exhausted: {exc}"
                ) from exc
            if attempt >= len(_RETRY_DELAYS):
                raise LLMError(f"Rate limit exceeded after retries: {exc}") from exc
            retry_after = _parse_retry_after(exc)
            actual_delay = max(delay if attempt >= 0 else 5, retry_after)
            time.sleep(actual_delay)
            continue

        except (openai.InternalServerError, openai.APIConnectionError,
                openai.APITimeoutError) as exc:
            if attempt >= len(_RETRY_DELAYS):
                raise LLMError(f"API error after retries: {exc}") from exc
            continue

    raise LLMError("Exhausted all retries")


def _is_daily_quota(exc: Exception) -> bool:
    body = str(exc).lower()
    return "perday" in body or "per day" in body or "daily" in body


def _parse_retry_after(exc: Exception) -> float:
    try:
        headers = exc.response.headers  # type: ignore[attr-defined]
        val = headers.get("retry-after") or headers.get("Retry-After")
        if val:
            return float(val)
    except Exception:
        pass
    return 0.0


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
def complete_json(prompt_name: str, variables: dict, *, tag: str,
                  temperature: float | None = None) -> dict:
    system_msg, user_msg = _load_prompt(prompt_name, variables)
    messages: list[dict] = []
    if system_msg:
        messages.append({"role": "system", "content": system_msg})
    messages.append({"role": "user", "content": user_msg})

    eff_model = _resolve_model(tag)
    eff_temp: float | str = _TEMPERATURE if temperature is None else temperature
    use_json = _JSON_MODE == "json_object"

    key = _cache_key(eff_model, messages, eff_temp, _MAX_TOKENS, _JSON_MODE)
    cached_entry = _cache_load(key)
    if cached_entry:
        _log_usage(tag, cached_entry["model"], True,
                   cached_entry["usage"]["prompt_tokens"],
                   cached_entry["usage"]["completion_tokens"],
                   cached_entry["usage"]["total_tokens"], 0.0)
        return _parse_json_object(cached_entry["response_text"])

    _check_budget()
    _wait_for_rate_limit()
    client = _client()
    t0 = time.monotonic()
    content, finish_reason, usage = _call_api(
        client, eff_model, messages, eff_temp, _MAX_TOKENS, use_json
    )
    latency = time.monotonic() - t0

    if finish_reason == "length":
        raise LLMError(
            f"[{tag}] Response truncated (finish_reason=length). "
            "Raise LLM_MAX_TOKENS to get a complete answer."
        )

    _cache_save(key, {"model": eff_model, "messages": messages,
                      "temperature": eff_temp, "max_tokens": _MAX_TOKENS,
                      "response_text": content, "finish_reason": finish_reason,
                      "usage": usage})
    _log_usage(tag, eff_model, False,
               usage["prompt_tokens"], usage["completion_tokens"],
               usage["total_tokens"], latency)

    try:
        return _parse_json_object(content)
    except ValueError as first_exc:
        repair_messages = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content": (
                f"That was not valid JSON. Parse error: {first_exc}\n"
                "Reply with valid JSON only, no explanation, no markdown fences."
            )},
        ]
        _check_budget()
        _wait_for_rate_limit()
        t0 = time.monotonic()
        content2, finish_reason2, usage2 = _call_api(
            client, eff_model, repair_messages, eff_temp, _MAX_TOKENS, use_json
        )
        latency2 = time.monotonic() - t0
        _log_usage(tag + ":repair", eff_model, False,
                   usage2["prompt_tokens"], usage2["completion_tokens"],
                   usage2["total_tokens"], latency2)
        try:
            return _parse_json_object(content2)
        except ValueError:
            raise LLMError(
                f"[{tag}] JSON parsing failed after repair. "
                f"First 300 chars: {content[:300]!r}"
            )


def complete_text(prompt_name: str, variables: dict, *, tag: str,
                  temperature: float | None = None) -> str:
    system_msg, user_msg = _load_prompt(prompt_name, variables)
    messages: list[dict] = []
    if system_msg:
        messages.append({"role": "system", "content": system_msg})
    messages.append({"role": "user", "content": user_msg})

    eff_model = _resolve_model(tag)
    eff_temp: float | str = _TEMPERATURE if temperature is None else temperature
    use_json = _JSON_MODE == "json_object"

    key = _cache_key(eff_model, messages, eff_temp, _MAX_TOKENS, _JSON_MODE)
    cached_entry = _cache_load(key)
    if cached_entry:
        _log_usage(tag, cached_entry["model"], True,
                   cached_entry["usage"]["prompt_tokens"],
                   cached_entry["usage"]["completion_tokens"],
                   cached_entry["usage"]["total_tokens"], 0.0)
        return cached_entry["response_text"]

    _check_budget()
    _wait_for_rate_limit()
    client = _client()
    t0 = time.monotonic()
    content, finish_reason, usage = _call_api(
        client, eff_model, messages, eff_temp, _MAX_TOKENS, use_json
    )
    latency = time.monotonic() - t0

    if finish_reason == "length":
        raise LLMError(
            f"[{tag}] Response truncated (finish_reason=length). "
            "Raise LLM_MAX_TOKENS to get a complete answer."
        )

    _cache_save(key, {"model": eff_model, "messages": messages,
                      "temperature": eff_temp, "max_tokens": _MAX_TOKENS,
                      "response_text": content, "finish_reason": finish_reason,
                      "usage": usage})
    _log_usage(tag, eff_model, False,
               usage["prompt_tokens"], usage["completion_tokens"],
               usage["total_tokens"], latency)
    return content


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main() -> None:
    import sys
    from urllib.parse import urlparse

    args = sys.argv[1:]
    if "--ping" in args:
        host = urlparse(_BASE_URL).netloc or _BASE_URL
        ping_model = _resolve_model("ping")
        has_headers = _EXTRA_HEADERS_STR is not None

        print(f"Endpoint       : {host}")
        print(f"Model (ping)   : {ping_model}")
        print(f"Temperature    : {_TEMPERATURE_STR}")
        print(f"JSON mode      : {_JSON_MODE}")
        print(f"Extra headers  : {'yes (values hidden)' if has_headers else 'no'}")
        print()

        t0 = time.monotonic()
        result = complete_json("ping", {"word": "promo"}, tag="ping")
        latency = time.monotonic() - t0
        rows = list(csv.DictReader(_LOG_PATH.open(encoding="utf-8")))
        last = rows[-1]
        cost_str = last.get("cost_usd", "")
        print(f"Result         : {result}")
        print(f"Tokens         : prompt={last['prompt_tokens']} "
              f"completion={last['completion_tokens']} "
              f"total={last['total_tokens']}")
        print(f"Cost           : {'$' + cost_str if cost_str else 'unknown'}")
        print(f"Latency        : {latency:.2f}s")
        print(f"Cached         : {last['cached']}")
        print()

        t0 = time.monotonic()
        result2 = complete_json("ping", {"word": "promo"}, tag="ping")
        latency2 = time.monotonic() - t0
        rows2 = list(csv.DictReader(_LOG_PATH.open(encoding="utf-8")))
        last2 = rows2[-1]
        print(f"Result         : {result2}")
        print(f"Latency        : {latency2:.4f}s")
        print(f"Cached         : {last2['cached']}  ← should be true")

    elif "--spend" in args:
        if not _LOG_PATH.exists():
            print("No usage log found.")
            sys.exit(0)
        total = 0.0
        by_model: dict[str, float] = {}
        by_stage: dict[str, float] = {}
        unknown_models: set[str] = set()
        with _LOG_PATH.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cost_str = row.get("cost_usd", "")
                if not cost_str:
                    m = row.get("model", "")
                    if m:
                        unknown_models.add(m)
                    continue
                cost = float(cost_str)
                total += cost
                m = row.get("model", "unknown")
                by_model[m] = by_model.get(m, 0.0) + cost
                tag = row.get("tag", "")
                stage = tag.split(":")[0] if tag else "unknown"
                by_stage[stage] = by_stage.get(stage, 0.0) + cost
        print(f"Total spend : ${total:.4f}")
        print("\nBy model:")
        for m, c in sorted(by_model.items()):
            print(f"  {m}: ${c:.4f}")
        print("\nBy stage:")
        for s, c in sorted(by_stage.items()):
            print(f"  {s}: ${c:.4f}")
        if unknown_models:
            print(f"\nNote: cost unknown for model(s): {sorted(unknown_models)}")

    elif "--list-models" in args:
        client = _client()
        try:
            models = list(client.models.list())
            names = sorted(m.id for m in models)
            for name in names:
                print(name)
        except Exception as exc:
            print(f"Could not list models: {exc}")
    else:
        print("Usage: python -m promo_finder.llm [--ping | --spend | --list-models]")


if __name__ == "__main__":
    _main()

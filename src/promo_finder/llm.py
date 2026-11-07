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

_REPO_ROOT = Path(__file__).parent.parent.parent
_PROMPTS_DIR = _REPO_ROOT / "prompts"
_CACHE_DIR = _REPO_ROOT / "cache" / "llm"
_LOG_PATH = _REPO_ROOT / "logs" / "llm_usage.csv"

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_last_call_time: float = 0.0
_json_mode_rejected: bool = False


class LLMError(RuntimeError):
    pass


class LLMQuotaExhausted(LLMError):
    """Raised when the daily API quota is exhausted. No point retrying."""
    pass


# ---------------------------------------------------------------------------
# Client factory (replaceable in tests)
# ---------------------------------------------------------------------------
def _client() -> openai.OpenAI:
    return openai.OpenAI(base_url=_BASE_URL, api_key=_API_KEY)


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
            raise LLMError(f"Prompt '{prompt_name}' uses placeholder '{{{{{name}}}}}' but it was not supplied")
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
def _cache_key(model: str, messages: list[dict], temperature: float,
               max_tokens: int, json_mode: bool) -> str:
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
def _log_usage(tag: str, model: str, cached: bool, prompt_tokens: int,
               completion_tokens: int, total_tokens: int, latency_s: float) -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not _LOG_PATH.exists()
    with _LOG_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["time", "tag", "model", "cached",
                             "prompt_tokens", "completion_tokens", "total_tokens", "latency_s"])
        writer.writerow([
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            tag, model, str(cached).lower(),
            prompt_tokens, completion_tokens, total_tokens,
            f"{latency_s:.3f}",
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
# Core call with retry
# ---------------------------------------------------------------------------
_RETRY_DELAYS = [5, 10, 20, 40, 80]


def _call_api(client: openai.OpenAI, messages: list[dict], temperature: float,
              max_tokens: int, use_json_mode: bool) -> tuple[str, str, dict]:
    """Return (content, finish_reason, usage_dict). May raise LLMError."""
    global _json_mode_rejected

    kwargs: dict[str, Any] = {
        "model": _MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
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
                # retry immediately without response_format
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
    """Return True if a RateLimitError indicates the daily quota is exhausted."""
    body = str(exc).lower()
    return "perday" in body or "per day" in body or "daily" in body


def _parse_retry_after(exc: Exception) -> float:
    """Extract Retry-After seconds from exception headers if available."""
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
                  temperature: float = 0.0) -> dict:
    system_msg, user_msg = _load_prompt(prompt_name, variables)
    messages: list[dict] = []
    if system_msg:
        messages.append({"role": "system", "content": system_msg})
    messages.append({"role": "user", "content": user_msg})

    key = _cache_key(_MODEL, messages, temperature, _MAX_TOKENS, json_mode=True)
    cached_entry = _cache_load(key)
    if cached_entry:
        _log_usage(tag, cached_entry["model"], True,
                   cached_entry["usage"]["prompt_tokens"],
                   cached_entry["usage"]["completion_tokens"],
                   cached_entry["usage"]["total_tokens"], 0.0)
        return _parse_json_object(cached_entry["response_text"])

    _wait_for_rate_limit()
    client = _client()
    t0 = time.monotonic()
    content, finish_reason, usage = _call_api(
        client, messages, temperature, _MAX_TOKENS, use_json_mode=True
    )
    latency = time.monotonic() - t0

    if finish_reason == "length":
        raise LLMError(
            f"[{tag}] Response truncated (finish_reason=length). "
            "Raise LLM_MAX_TOKENS to get a complete answer."
        )

    _cache_save(key, {"model": _MODEL, "messages": messages,
                      "temperature": temperature, "max_tokens": _MAX_TOKENS,
                      "response_text": content, "finish_reason": finish_reason,
                      "usage": usage})
    _log_usage(tag, _MODEL, False,
               usage["prompt_tokens"], usage["completion_tokens"],
               usage["total_tokens"], latency)

    try:
        return _parse_json_object(content)
    except ValueError as first_exc:
        # one repair retry
        repair_messages = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content": (
                f"That was not valid JSON. Parse error: {first_exc}\n"
                "Reply with valid JSON only, no explanation, no markdown fences."
            )},
        ]
        _wait_for_rate_limit()
        t0 = time.monotonic()
        content2, finish_reason2, usage2 = _call_api(
            client, repair_messages, temperature, _MAX_TOKENS, use_json_mode=True
        )
        latency2 = time.monotonic() - t0
        _log_usage(tag + ":repair", _MODEL, False,
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
                  temperature: float = 0.0) -> str:
    system_msg, user_msg = _load_prompt(prompt_name, variables)
    messages: list[dict] = []
    if system_msg:
        messages.append({"role": "system", "content": system_msg})
    messages.append({"role": "user", "content": user_msg})

    key = _cache_key(_MODEL, messages, temperature, _MAX_TOKENS, json_mode=False)
    cached_entry = _cache_load(key)
    if cached_entry:
        _log_usage(tag, cached_entry["model"], True,
                   cached_entry["usage"]["prompt_tokens"],
                   cached_entry["usage"]["completion_tokens"],
                   cached_entry["usage"]["total_tokens"], 0.0)
        return cached_entry["response_text"]

    _wait_for_rate_limit()
    client = _client()
    t0 = time.monotonic()
    content, finish_reason, usage = _call_api(
        client, messages, temperature, _MAX_TOKENS, use_json_mode=False
    )
    latency = time.monotonic() - t0

    if finish_reason == "length":
        raise LLMError(
            f"[{tag}] Response truncated (finish_reason=length). "
            "Raise LLM_MAX_TOKENS to get a complete answer."
        )

    _cache_save(key, {"model": _MODEL, "messages": messages,
                      "temperature": temperature, "max_tokens": _MAX_TOKENS,
                      "response_text": content, "finish_reason": finish_reason,
                      "usage": usage})
    _log_usage(tag, _MODEL, False,
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
        print(f"Endpoint : {host}")
        print(f"Model    : {_MODEL}")
        print()

        t0 = time.monotonic()
        result = complete_json("ping", {"word": "promo"}, tag="ping")
        latency = time.monotonic() - t0
        # read usage from last log row
        rows = list(csv.DictReader(_LOG_PATH.open(encoding="utf-8")))
        last = rows[-1]
        print(f"Result   : {result}")
        print(f"Tokens   : prompt={last['prompt_tokens']} "
              f"completion={last['completion_tokens']} "
              f"total={last['total_tokens']}")
        print(f"Latency  : {latency:.2f}s")
        print(f"Cached   : {last['cached']}")
        print()

        t0 = time.monotonic()
        result2 = complete_json("ping", {"word": "promo"}, tag="ping")
        latency2 = time.monotonic() - t0
        rows2 = list(csv.DictReader(_LOG_PATH.open(encoding="utf-8")))
        last2 = rows2[-1]
        print(f"Result   : {result2}")
        print(f"Latency  : {latency2:.4f}s")
        print(f"Cached   : {last2['cached']}  ← should be true")

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
        print("Usage: python -m promo_finder.llm [--ping | --list-models]")


if __name__ == "__main__":
    _main()

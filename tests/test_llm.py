"""Tests for llm.py — no network calls; _client() is replaced with a fake."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import promo_finder.llm as llm_mod
from promo_finder.llm import LLMError, _load_prompt, _parse_json_object

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_choice(content: str, finish_reason: str = "stop") -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = finish_reason
    return choice


def _make_response(content: str, finish_reason: str = "stop",
                   prompt_tokens: int = 10, completion_tokens: int = 5) -> MagicMock:
    resp = MagicMock()
    resp.choices = [_make_choice(content, finish_reason)]
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    resp.usage.total_tokens = prompt_tokens + completion_tokens
    return resp


def _fake_client(responses: list) -> MagicMock:
    """Return a mock OpenAI client whose chat.completions.create returns responses in order."""
    client = MagicMock()
    client.chat.completions.create.side_effect = responses
    return client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_state(tmp_path, monkeypatch):
    """Point cache/log to tmp, reset module-level state before each test."""
    monkeypatch.setattr(llm_mod, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(llm_mod, "_LOG_PATH", tmp_path / "llm_usage.csv")
    monkeypatch.setattr(llm_mod, "_CACHE_ENABLED", True)
    monkeypatch.setattr(llm_mod, "_json_mode_rejected", False)
    monkeypatch.setattr(llm_mod, "_last_call_time", 0.0)
    monkeypatch.setattr(llm_mod, "_MIN_INTERVAL", 0.0)


@pytest.fixture()
def ping_prompt(tmp_path, monkeypatch):
    """Create a minimal ping prompt and point PROMPTS_DIR at it."""
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "ping.md").write_text("Reply with {{word}}.", encoding="utf-8")
    monkeypatch.setattr(llm_mod, "_PROMPTS_DIR", prompts)
    return prompts


# ---------------------------------------------------------------------------
# 1. Templating
# ---------------------------------------------------------------------------

def test_template_fills_values(tmp_path, monkeypatch):
    p = tmp_path / "tpl.md"
    p.write_text("Hello {{name}}, you are {{age}}.", encoding="utf-8")
    monkeypatch.setattr(llm_mod, "_PROMPTS_DIR", tmp_path)
    sys_msg, user_msg = _load_prompt("tpl", {"name": "Alice", "age": "30"})
    assert sys_msg is None
    assert user_msg == "Hello Alice, you are 30."


def test_template_missing_variable_raises(tmp_path, monkeypatch):
    p = tmp_path / "tpl.md"
    p.write_text("{{a}} and {{b}}", encoding="utf-8")
    monkeypatch.setattr(llm_mod, "_PROMPTS_DIR", tmp_path)
    with pytest.raises(LLMError, match=r"\bb\b"):
        _load_prompt("tpl", {"a": "1"})


def test_template_unused_variable_raises(tmp_path, monkeypatch):
    p = tmp_path / "tpl.md"
    p.write_text("{{a}}", encoding="utf-8")
    monkeypatch.setattr(llm_mod, "_PROMPTS_DIR", tmp_path)
    with pytest.raises(LLMError, match="not used"):
        _load_prompt("tpl", {"a": "1", "extra": "oops"})


def test_template_json_braces_survive(tmp_path, monkeypatch):
    p = tmp_path / "tpl.md"
    p.write_text('{"key": "{{val}}"}', encoding="utf-8")
    monkeypatch.setattr(llm_mod, "_PROMPTS_DIR", tmp_path)
    _, user_msg = _load_prompt("tpl", {"val": "hello"})
    assert user_msg == '{"key": "hello"}'


# ---------------------------------------------------------------------------
# 2. System/user split
# ---------------------------------------------------------------------------

def test_system_user_split(tmp_path, monkeypatch):
    p = tmp_path / "split.md"
    p.write_text("You are a bot.\n---USER---\nSay {{x}}.", encoding="utf-8")
    monkeypatch.setattr(llm_mod, "_PROMPTS_DIR", tmp_path)
    sys_msg, user_msg = _load_prompt("split", {"x": "hi"})
    assert sys_msg == "You are a bot."
    assert user_msg == "Say hi."


# ---------------------------------------------------------------------------
# 3. Second identical call served from cache (fake client called once)
# ---------------------------------------------------------------------------

def test_cache_hit_on_second_call(ping_prompt, monkeypatch):
    client = _fake_client([_make_response('{"ok": true, "echo": "promo"}')])
    monkeypatch.setattr(llm_mod, "_client", lambda: client)

    r1 = llm_mod.complete_json("ping", {"word": "promo"}, tag="t1")
    r2 = llm_mod.complete_json("ping", {"word": "promo"}, tag="t1")

    assert r1 == r2 == {"ok": True, "echo": "promo"}
    assert client.chat.completions.create.call_count == 1


# ---------------------------------------------------------------------------
# 4. Different model name → cache miss
# ---------------------------------------------------------------------------

def test_different_model_cache_miss(ping_prompt, monkeypatch):
    resp = _make_response('{"ok": true, "echo": "promo"}')
    client = _fake_client([resp, resp])
    monkeypatch.setattr(llm_mod, "_client", lambda: client)

    monkeypatch.setattr(llm_mod, "_MODEL", "model-a")
    llm_mod.complete_json("ping", {"word": "promo"}, tag="t")

    monkeypatch.setattr(llm_mod, "_MODEL", "model-b")
    llm_mod.complete_json("ping", {"word": "promo"}, tag="t")

    assert client.chat.completions.create.call_count == 2


# ---------------------------------------------------------------------------
# 5. Fenced ```json reply is parsed
# ---------------------------------------------------------------------------

def test_fenced_json_reply(ping_prompt, monkeypatch):
    fenced = '```json\n{"ok": true, "echo": "promo"}\n```'
    client = _fake_client([_make_response(fenced)])
    monkeypatch.setattr(llm_mod, "_client", lambda: client)
    r = llm_mod.complete_json("ping", {"word": "promo"}, tag="t")
    assert r == {"ok": True, "echo": "promo"}


# ---------------------------------------------------------------------------
# 6. Invalid JSON → one repair call → success; invalid twice → LLMError
# ---------------------------------------------------------------------------

def test_invalid_json_repaired(ping_prompt, monkeypatch):
    bad = "This is not JSON at all"
    good = '{"ok": true, "echo": "promo"}'
    client = _fake_client([_make_response(bad), _make_response(good)])
    monkeypatch.setattr(llm_mod, "_client", lambda: client)
    r = llm_mod.complete_json("ping", {"word": "promo"}, tag="t")
    assert r == {"ok": True, "echo": "promo"}
    assert client.chat.completions.create.call_count == 2


def test_invalid_json_twice_raises(ping_prompt, monkeypatch):
    bad = "not json"
    client = _fake_client([_make_response(bad), _make_response("also bad")])
    monkeypatch.setattr(llm_mod, "_client", lambda: client)
    with pytest.raises(LLMError, match="JSON parsing failed"):
        llm_mod.complete_json("ping", {"word": "promo"}, tag="t")


# ---------------------------------------------------------------------------
# 7. finish_reason == "length" → LLMError
# ---------------------------------------------------------------------------

def test_finish_reason_length_raises(ping_prompt, monkeypatch):
    client = _fake_client([_make_response('{"partial":', finish_reason="length")])
    monkeypatch.setattr(llm_mod, "_client", lambda: client)
    with pytest.raises(LLMError, match="LLM_MAX_TOKENS"):
        llm_mod.complete_json("ping", {"word": "promo"}, tag="t")


# ---------------------------------------------------------------------------
# 8. HTTP 429 then success → retried; 401 → no retry
# ---------------------------------------------------------------------------

def _make_http_exc(cls, message: str, status: int = 400) -> Any:
    """Create a real openai HTTP exception instance."""
    import httpx2
    req = httpx2.Request("POST", "https://test.example.com")
    resp = httpx2.Response(status, headers={}, content=message.encode(), request=req)
    return cls(message, response=resp, body=None)


def test_429_retried(ping_prompt, monkeypatch):
    import openai as openai_mod

    good_resp = _make_response('{"ok": true, "echo": "promo"}')
    rate_exc = _make_http_exc(openai_mod.RateLimitError, "rate limited", 429)

    client = MagicMock()
    client.chat.completions.create.side_effect = [rate_exc, good_resp]

    monkeypatch.setattr(llm_mod, "_client", lambda: client)
    monkeypatch.setattr(llm_mod, "_RETRY_DELAYS", [0])

    with patch("time.sleep"):
        r = llm_mod.complete_json("ping", {"word": "promo"}, tag="t")
    assert r == {"ok": True, "echo": "promo"}
    assert client.chat.completions.create.call_count == 2


def test_401_no_retry(ping_prompt, monkeypatch):
    import openai as openai_mod

    auth_exc = _make_http_exc(openai_mod.AuthenticationError, "bad key", 401)

    client = MagicMock()
    client.chat.completions.create.side_effect = [auth_exc]

    monkeypatch.setattr(llm_mod, "_client", lambda: client)

    with pytest.raises(LLMError, match="[Aa]uth"):
        llm_mod.complete_json("ping", {"word": "promo"}, tag="t")

    assert client.chat.completions.create.call_count == 1


# ---------------------------------------------------------------------------
# 9. response_format rejected → retried without it
# ---------------------------------------------------------------------------

def test_response_format_rejected(ping_prompt, monkeypatch):
    import openai as openai_mod

    bad_req = _make_http_exc(
        openai_mod.BadRequestError, "response_format is not supported", 400
    )
    good_resp = _make_response('{"ok": true, "echo": "promo"}')

    client = MagicMock()
    client.chat.completions.create.side_effect = [bad_req, good_resp]
    monkeypatch.setattr(llm_mod, "_client", lambda: client)

    r = llm_mod.complete_json("ping", {"word": "promo"}, tag="t")
    assert r == {"ok": True, "echo": "promo"}

    # second call should not include response_format (flag was set)
    second_call_kwargs = client.chat.completions.create.call_args_list[1][1]
    assert "response_format" not in second_call_kwargs


# ---------------------------------------------------------------------------
# 10. Usage CSV gets a row per call
# ---------------------------------------------------------------------------

def test_usage_csv_row_per_call(ping_prompt, monkeypatch):
    resp = _make_response('{"ok": true, "echo": "promo"}')
    client = _fake_client([resp])
    monkeypatch.setattr(llm_mod, "_client", lambda: client)

    llm_mod.complete_json("ping", {"word": "promo"}, tag="first-call")
    # second call is cached
    llm_mod.complete_json("ping", {"word": "promo"}, tag="second-call")

    rows = list(csv.DictReader(llm_mod._LOG_PATH.open(encoding="utf-8")))
    assert len(rows) == 2
    assert rows[0]["cached"] == "false"
    assert rows[1]["cached"] == "true"
    assert rows[0]["tag"] == "first-call"
    assert rows[1]["tag"] == "second-call"

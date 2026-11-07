"""Tests for beats.py, scriptfmt.py, and eval_beats.py (fake LLM, no network)."""
from __future__ import annotations

from pathlib import Path

import pytest

from promo_finder.scriptfmt import format_blocks
from promo_finder.beats import _validate_response, _find_clean_start, run_beats
from promo_finder.eval_beats import run_evals


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_block(
    bid: str,
    btype: str,
    start: float,
    end: float,
    text: str = "...",
    label_raw: str | None = None,
    scene_id: str = "E01-S01",
) -> dict:
    if label_raw is None:
        label_raw = "CAMERA" if btype != "DIALOGUE" else "SPEAKER"
    return {
        "id": bid, "type": btype, "start": start, "end": end, "text": text,
        "label_raw": label_raw, "scene_id": scene_id, "episode": int(bid.split("-")[0][1:]),
    }


def _make_ep(ep_num: int, blocks: list[dict], duration: float = 60.0) -> dict:
    return {
        "episode": ep_num,
        "logline": "Test logline.",
        "continuity_notes": "",
        "scenes": [{"id": f"E{ep_num:02d}-S01", "heading": "INT. ROOM – DAY", "start": 0.0, "end": duration}],
        "blocks": blocks,
        "duration": duration,
    }


def _good_hook(bid: str) -> dict:
    return {"block_id": bid, "type": "reveal", "stop_power": 4, "why": "Big reveal", "context_needed": "none"}


def _good_cliff(bid: str) -> dict:
    return {"block_id": bid, "tension": 4, "open_question": "What happens next?"}


def _good_ending() -> dict:
    return {"ends_on_cliffhanger": True, "ending_type": "cliffhanger", "note": "tension"}


# ---------------------------------------------------------------------------
# 1. Formatter: scene lines, dialogue label, block order
# ---------------------------------------------------------------------------

def test_formatter_scene_header():
    blocks = [
        _make_block("E01-B001", "CAMERA", 0.0, 2.0, "Wide shot.", scene_id="E01-S01"),
        _make_block("E01-B002", "CAMERA", 2.0, 4.0, "Close-up.", scene_id="E01-S02"),
    ]
    scenes = {
        "E01-S01": {"id": "E01-S01", "heading": "INT. CHURCH – DAY"},
        "E01-S02": {"id": "E01-S02", "heading": "INT. HALL – NIGHT"},
    }
    result = format_blocks(blocks, scenes)
    lines = result.splitlines()
    assert lines[0] == "== SCENE E01-S01: INT. CHURCH – DAY =="
    assert "E01-B001" in lines[1]
    assert lines[2] == "== SCENE E01-S02: INT. HALL – NIGHT =="
    assert "E01-B002" in lines[3]


def test_formatter_dialogue_label():
    blocks = [
        _make_block("E01-B001", "DIALOGUE", 0.0, 2.0,
                    "No.", label_raw="MATRIARCH (Cold, Commanding)", scene_id="E01-S01"),
    ]
    result = format_blocks(blocks)
    assert "MATRIARCH (Cold, Commanding): No." in result


def test_formatter_non_dialogue_no_label():
    blocks = [
        _make_block("E01-B001", "CAMERA", 0.0, 2.0, "Doors open.", scene_id="E01-S01"),
    ]
    result = format_blocks(blocks)
    assert "CAMERA | Doors open." in result
    assert ":" not in result.split("CAMERA | ")[1]


def test_formatter_block_order():
    blocks = [
        _make_block("E01-B001", "CAMERA", 0.0, 1.0, "A", scene_id="E01-S01"),
        _make_block("E01-B002", "CAMERA", 1.0, 2.0, "B", scene_id="E01-S01"),
        _make_block("E01-B003", "CAMERA", 2.0, 3.0, "C", scene_id="E01-S01"),
    ]
    result = format_blocks(blocks)
    pos1 = result.index("E01-B001")
    pos2 = result.index("E01-B002")
    pos3 = result.index("E01-B003")
    assert pos1 < pos2 < pos3


# ---------------------------------------------------------------------------
# 2. Made-up ID and cross-episode ID → invalid_id
# ---------------------------------------------------------------------------

def test_invalid_id_made_up():
    block_ids = {"E01-B001", "E01-B002"}
    raw = {
        "hooks": [
            _good_hook("E01-B001"),           # valid
            _good_hook("E01-BFAKE"),           # made-up
            _good_hook("E99-B001"),            # wrong episode
        ],
        "cliffhangers": [],
        "ending": _good_ending(),
    }
    validated, errors = _validate_response(raw, 1, block_ids)
    assert len(validated["hooks"]) == 1
    assert validated["hooks"][0]["block_id"] == "E01-B001"
    assert validated["_invalid_id"] == 2
    assert any("E01-BFAKE" in e for e in errors)
    assert any("E99-B001" in e for e in errors)


def test_invalid_id_in_cliffhangers():
    block_ids = {"E01-B001"}
    raw = {
        "hooks": [],
        "cliffhangers": [_good_cliff("E01-B999")],  # doesn't exist
        "ending": _good_ending(),
    }
    validated, errors = _validate_response(raw, 1, block_ids)
    assert len(validated["cliffhangers"]) == 0
    assert validated["_invalid_id"] == 1


# ---------------------------------------------------------------------------
# 3. Bad type or score out of range → invalid_item
# ---------------------------------------------------------------------------

def test_bad_hook_type():
    block_ids = {"E01-B001"}
    raw = {
        "hooks": [{"block_id": "E01-B001", "type": "BADTYPE", "stop_power": 4,
                   "why": "...", "context_needed": "none"}],
        "cliffhangers": [],
        "ending": _good_ending(),
    }
    validated, _ = _validate_response(raw, 1, block_ids)
    assert len(validated["hooks"]) == 0
    assert validated["_invalid_item"] == 1


def test_bad_stop_power():
    block_ids = {"E01-B001"}
    raw = {
        "hooks": [{"block_id": "E01-B001", "type": "reveal", "stop_power": 9,
                   "why": "...", "context_needed": "none"}],
        "cliffhangers": [],
        "ending": _good_ending(),
    }
    validated, _ = _validate_response(raw, 1, block_ids)
    assert validated["_invalid_item"] == 1


def test_bad_tension():
    block_ids = {"E01-B001"}
    raw = {
        "hooks": [],
        "cliffhangers": [{"block_id": "E01-B001", "tension": 0,
                           "open_question": "?"}],
        "ending": _good_ending(),
    }
    validated, _ = _validate_response(raw, 1, block_ids)
    assert validated["_invalid_item"] == 1


def test_missing_required_field():
    block_ids = {"E01-B001"}
    raw = {
        "hooks": [{"block_id": "E01-B001", "type": "reveal", "stop_power": 3}],  # missing 'why'
        "cliffhangers": [],
        "ending": _good_ending(),
    }
    validated, _ = _validate_response(raw, 1, block_ids)
    assert validated["_invalid_item"] == 1


# ---------------------------------------------------------------------------
# 4. Duplicates removed; at most 5 kept
# ---------------------------------------------------------------------------

def test_dedup_keeps_first():
    block_ids = {f"E01-B{i:03d}" for i in range(1, 10)}
    raw = {
        "hooks": [
            _good_hook("E01-B001"),
            _good_hook("E01-B001"),  # dup
            _good_hook("E01-B002"),
        ],
        "cliffhangers": [],
        "ending": _good_ending(),
    }
    validated, _ = _validate_response(raw, 1, block_ids)
    assert len(validated["hooks"]) == 2
    assert validated["hooks"][0]["block_id"] == "E01-B001"


def test_at_most_5_kept():
    block_ids = {f"E01-B{i:03d}" for i in range(1, 10)}
    raw = {
        "hooks": [_good_hook(f"E01-B{i:03d}") for i in range(1, 8)],  # 7 items
        "cliffhangers": [],
        "ending": _good_ending(),
    }
    validated, _ = _validate_response(raw, 1, block_ids)
    assert len(validated["hooks"]) == 5


def test_at_most_5_cliffhangers():
    block_ids = {f"E01-B{i:03d}" for i in range(1, 10)}
    raw = {
        "hooks": [],
        "cliffhangers": [_good_cliff(f"E01-B{i:03d}") for i in range(1, 8)],
        "ending": _good_ending(),
    }
    validated, _ = _validate_response(raw, 1, block_ids)
    assert len(validated["cliffhangers"]) == 5


# ---------------------------------------------------------------------------
# 5. clean_start logic
# ---------------------------------------------------------------------------

def test_clean_start_at_hook_start():
    # Hook at 10.0, no straddling dialogue → clean_start = 10.0
    blocks = [
        _make_block("E01-B001", "CAMERA", 0.0, 10.0),
        _make_block("E01-B002", "CAMERA", 10.0, 12.0),
    ]
    result = _find_clean_start(10.0, blocks)
    assert result == 10.0


def test_clean_start_steps_back_over_dialogue():
    # Hook at 10.0s, dialogue from 8.0-12.0 (hook is mid-dialogue)
    # Previous clean cut: 8.0 (start of dialogue / end of camera), within 3s
    blocks = [
        _make_block("E01-B001", "CAMERA", 0.0, 8.0),
        _make_block("E01-B002", "DIALOGUE", 8.0, 12.0, label_raw="SPEAKER"),
        _make_block("E01-B003", "CAMERA", 10.0, 11.0),
    ]
    result = _find_clean_start(10.0, blocks)
    assert result == pytest.approx(8.0)


def test_clean_start_null_when_too_far_back():
    # Hook at 10.0s, dialogue from 5.0-11.0 (clean cut at 5.0 is 5s back > 3s)
    blocks = [
        _make_block("E01-B001", "CAMERA", 0.0, 5.0),
        _make_block("E01-B002", "DIALOGUE", 5.0, 11.0, label_raw="SPEAKER"),
        _make_block("E01-B003", "CAMERA", 10.0, 11.0),
    ]
    result = _find_clean_start(10.0, blocks)
    assert result is None


def test_clean_start_uses_latest_candidate():
    # Hook at 10.0, two possible clean cuts at 8.5 and 7.5 — should pick 8.5 (latest)
    blocks = [
        _make_block("E01-B001", "CAMERA", 0.0, 7.5),
        _make_block("E01-B002", "CAMERA", 7.5, 8.5),
        _make_block("E01-B003", "CAMERA", 8.5, 10.0),
        _make_block("E01-B004", "DIALOGUE", 10.0, 12.0, label_raw="SPEAKER"),
    ]
    result = _find_clean_start(10.0, blocks)
    assert result == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# 6. LLMError on one episode doesn't stop others
# ---------------------------------------------------------------------------

def test_llm_error_continues(monkeypatch):
    import promo_finder.beats as beats_mod
    from promo_finder.llm import LLMError

    def fake_complete_json(prompt_name, variables, *, tag, temperature=0.0):
        ep = int(variables["episode"])
        if ep == 1:
            raise LLMError("API down")
        return {
            "episode": ep,
            "hooks": [],
            "cliffhangers": [],
            "ending": {"ends_on_cliffhanger": False, "ending_type": "resolved", "note": "ok"},
        }

    monkeypatch.setattr(beats_mod, "complete_json", fake_complete_json)

    ep1 = _make_ep(1, [])
    ep2 = _make_ep(2, [])
    results, quota_remaining = beats_mod.run_beats([ep1, ep2])

    assert len(results) == 2
    assert any("LLMError" in e for e in results[0]["errors"])
    assert results[1]["errors"] == []
    assert quota_remaining == []


# ---------------------------------------------------------------------------
# LLMQuotaExhausted stops the run; prior results and remaining list returned
# ---------------------------------------------------------------------------

def test_quota_exhausted_stops_run(monkeypatch):
    import promo_finder.beats as beats_mod
    from promo_finder.llm import LLMQuotaExhausted

    def fake_complete_json(prompt_name, variables, *, tag, temperature=0.0):
        ep = int(variables["episode"])
        if ep == 2:
            raise LLMQuotaExhausted("PerDay quota exceeded")
        return {
            "episode": ep,
            "hooks": [],
            "cliffhangers": [],
            "ending": {"ends_on_cliffhanger": False, "ending_type": "resolved", "note": "ok"},
        }

    monkeypatch.setattr(beats_mod, "complete_json", fake_complete_json)

    ep1 = _make_ep(1, [])
    ep2 = _make_ep(2, [])
    ep3 = _make_ep(3, [])
    results, quota_remaining = beats_mod.run_beats([ep1, ep2, ep3])

    # E01 succeeded, E02 triggered quota → stop; E03 never attempted
    assert len(results) == 1
    assert results[0]["episode"] == 1
    assert quota_remaining == [2, 3]


def test_quota_exhausted_on_first_episode(monkeypatch):
    import promo_finder.beats as beats_mod
    from promo_finder.llm import LLMQuotaExhausted

    def fake_complete_json(prompt_name, variables, *, tag, temperature=0.0):
        raise LLMQuotaExhausted("per day limit")

    monkeypatch.setattr(beats_mod, "complete_json", fake_complete_json)

    ep1 = _make_ep(1, [])
    ep2 = _make_ep(2, [])
    results, quota_remaining = beats_mod.run_beats([ep1, ep2])

    assert results == []
    assert quota_remaining == [1, 2]


def test_is_daily_quota_detection():
    from promo_finder.llm import _is_daily_quota

    class FakeExc(Exception):
        pass

    assert _is_daily_quota(FakeExc("PerDay quota exceeded"))
    assert _is_daily_quota(FakeExc("exceeded per day limit"))
    assert _is_daily_quota(FakeExc("daily quota exhausted"))
    assert not _is_daily_quota(FakeExc("rate limit per minute"))
    assert not _is_daily_quota(FakeExc("too many requests"))


# ---------------------------------------------------------------------------
# 7. Eval checks: PASS and FAIL cases on fake beats
# ---------------------------------------------------------------------------

class _FakeShow:
    def episode_duration(self, ep_num: int) -> float:
        return 60.0


def test_eval_resolved_ending_pass(tmp_path):
    spec = {"resolved_or_soft_endings": [7], "min_top_hook_power": [], "cliff_types_near_end": []}
    evals_path = tmp_path / "show.json"
    evals_path.write_text(__import__("json").dumps(spec))

    results = [{"episode": 7, "hooks": [], "cliffhangers": [],
                "ending": {"ends_on_cliffhanger": False, "ending_type": "resolved", "note": ""},
                "errors": [], "stats": {}}]
    checks = run_evals(results, _FakeShow(), evals_path)
    assert len(checks) == 1
    assert checks[0]["status"] == "PASS"


def test_eval_resolved_ending_fail(tmp_path):
    spec = {"resolved_or_soft_endings": [7], "min_top_hook_power": [], "cliff_types_near_end": []}
    evals_path = tmp_path / "show.json"
    evals_path.write_text(__import__("json").dumps(spec))

    results = [{"episode": 7, "hooks": [], "cliffhangers": [],
                "ending": {"ends_on_cliffhanger": True, "ending_type": "cliffhanger", "note": ""},
                "errors": [], "stats": {}}]
    checks = run_evals(results, _FakeShow(), evals_path)
    assert checks[0]["status"] == "FAIL"


def test_eval_min_hook_power_pass(tmp_path):
    spec = {"resolved_or_soft_endings": [], "min_top_hook_power": [{"episode": 1, "min": 4}], "cliff_types_near_end": []}
    evals_path = tmp_path / "show.json"
    evals_path.write_text(__import__("json").dumps(spec))

    hook = {"block_id": "E01-B001", "type": "reveal", "stop_power": 5, "why": "...",
            "block_type": "DIALOGUE", "start": 10.0, "end": 12.0, "clean_start": 10.0}
    results = [{"episode": 1, "hooks": [hook], "cliffhangers": [],
                "ending": {}, "errors": [], "stats": {}}]
    checks = run_evals(results, _FakeShow(), evals_path)
    assert checks[0]["status"] == "PASS"


def test_eval_min_hook_power_fail(tmp_path):
    spec = {"resolved_or_soft_endings": [], "min_top_hook_power": [{"episode": 1, "min": 4}], "cliff_types_near_end": []}
    evals_path = tmp_path / "show.json"
    evals_path.write_text(__import__("json").dumps(spec))

    hook = {"block_id": "E01-B001", "type": "reveal", "stop_power": 2, "why": "...",
            "block_type": "DIALOGUE", "start": 10.0, "end": 12.0, "clean_start": 10.0}
    results = [{"episode": 1, "hooks": [hook], "cliffhangers": [],
                "ending": {}, "errors": [], "stats": {}}]
    checks = run_evals(results, _FakeShow(), evals_path)
    assert checks[0]["status"] == "FAIL"


def test_eval_cliff_type_near_end_pass(tmp_path):
    spec = {"resolved_or_soft_endings": [], "min_top_hook_power": [],
            "cliff_types_near_end": [{"episode": 23, "types": ["CAMERA", "SOUND_FX"], "within_last_s": 8.0}]}
    evals_path = tmp_path / "show.json"
    evals_path.write_text(__import__("json").dumps(spec))

    cliff = {"block_id": "E23-B080", "tension": 5, "open_question": "?",
             "block_type": "CAMERA", "start": 55.0, "end": 59.0}  # within last 8s of 60s ep
    results = [{"episode": 23, "hooks": [], "cliffhangers": [cliff],
                "ending": {}, "errors": [], "stats": {}}]
    checks = run_evals(results, _FakeShow(), evals_path)
    assert checks[0]["status"] == "PASS"


def test_eval_cliff_type_near_end_fail_type(tmp_path):
    spec = {"resolved_or_soft_endings": [], "min_top_hook_power": [],
            "cliff_types_near_end": [{"episode": 23, "types": ["CAMERA", "SOUND_FX"], "within_last_s": 8.0}]}
    evals_path = tmp_path / "show.json"
    evals_path.write_text(__import__("json").dumps(spec))

    cliff = {"block_id": "E23-B080", "tension": 5, "open_question": "?",
             "block_type": "DIALOGUE", "start": 55.0, "end": 59.0}  # wrong type
    results = [{"episode": 23, "hooks": [], "cliffhangers": [cliff],
                "ending": {}, "errors": [], "stats": {}}]
    checks = run_evals(results, _FakeShow(), evals_path)
    assert checks[0]["status"] == "FAIL"


def test_eval_cliff_type_near_end_fail_time(tmp_path):
    spec = {"resolved_or_soft_endings": [], "min_top_hook_power": [],
            "cliff_types_near_end": [{"episode": 23, "types": ["CAMERA"], "within_last_s": 8.0}]}
    evals_path = tmp_path / "show.json"
    evals_path.write_text(__import__("json").dumps(spec))

    cliff = {"block_id": "E23-B020", "tension": 3, "open_question": "?",
             "block_type": "CAMERA", "start": 20.0, "end": 25.0}  # too early (not in last 8s)
    results = [{"episode": 23, "hooks": [], "cliffhangers": [cliff],
                "ending": {}, "errors": [], "stats": {}}]
    checks = run_evals(results, _FakeShow(), evals_path)
    assert checks[0]["status"] == "FAIL"


def test_eval_missing_file(tmp_path):
    checks = run_evals([], _FakeShow(), tmp_path / "nonexistent.json")
    assert checks == []


def test_eval_episode_not_in_results(tmp_path):
    spec = {"resolved_or_soft_endings": [42], "min_top_hook_power": [], "cliff_types_near_end": []}
    evals_path = tmp_path / "show.json"
    evals_path.write_text(__import__("json").dumps(spec))

    checks = run_evals([], _FakeShow(), evals_path)
    assert checks[0]["status"] == "SKIP"

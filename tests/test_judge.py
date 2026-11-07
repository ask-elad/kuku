"""Tests for judge.py and format_clip (fake LLM, no network)."""
from __future__ import annotations

import random
from unittest.mock import patch

import pytest

from promo_finder.judge import _validate_response, run_judge
from promo_finder.scriptfmt import format_clip
from promo_finder.show import Show


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bl(bid: str, btype: str, start: float, end: float, text: str = "...",
        label_raw: str | None = None, scene_id: str | None = None) -> dict:
    ep_num = int(bid.split("-")[0][1:])
    return {
        "id": bid, "type": btype, "start": start, "end": end, "text": text,
        "label_raw": label_raw or ("SPEAKER" if btype == "DIALOGUE" else "CAMERA"),
        "scene_id": scene_id or f"E{ep_num:02d}-S01",
        "episode": ep_num,
    }


def _ep(ep_num: int, blocks: list[dict], scenes: list[dict] | None = None,
        dur: float = 120.0) -> dict:
    if scenes is None:
        scenes = [{"id": f"E{ep_num:02d}-S01",
                   "heading": "INT. HALL – DAY",
                   "start": 0.0, "end": dur}]
    return {
        "episode": ep_num, "logline": "Test.", "continuity_notes": "",
        "scenes": scenes, "blocks": blocks, "duration": dur,
    }


def _make_show(episodes: list[dict]) -> Show:
    return Show(title="Test Show", slug="test-show", episodes=episodes)


def _make_promo(pid: str, segments: list[dict],
                hook_bid: str, cliff_bid: str) -> dict:
    """Build a resolved promo dict (times already filled in)."""
    return {
        "promo_id": pid,
        "segments": segments,
        "hook": {"block_id": hook_bid, "at": segments[0]["start"]},
        "cliffhanger": {"block_id": cliff_bid, "at": segments[-1]["end"] - 3.0},
        "beat_notes": {"hook_why": "big", "hook_type": "reveal",
                       "stop_power": 4, "open_question": "?", "tension": 4},
        "why": "",
        "method": "pipeline",
        "duration": sum(s.get("duration", s["end"] - s["start"]) for s in segments),
        "checks": {"hard": {}, "soft": {}, "errors": [], "valid": True},
    }


def _seg(ep: int, start: float, end: float, start_bl: str, end_bl: str) -> dict:
    return {
        "start_block": start_bl, "end_block": end_bl,
        "episode": ep, "start": start, "end": end,
        "start_tc": "00:00.00", "end_tc": "00:30.00",
        "duration": end - start,
    }


# ---------------------------------------------------------------------------
# 5. format_clip
# ---------------------------------------------------------------------------

def test_format_clip_rebased_times():
    blocks = [
        _bl("E01-B001", "CAMERA", 10.0, 13.0, "Wide shot"),
        _bl("E01-B002", "DIALOGUE", 13.0, 18.0, "Hello", label_raw="ALICE"),
    ]
    show = _make_show([_ep(1, blocks)])
    seg = _seg(1, 10.0, 18.0, "E01-B001", "E01-B002")
    promo = _make_promo("C-E01-01", [seg], "E01-B001", "E01-B002")

    text = format_clip(promo, show)
    # Times should start at 00:00
    assert "00:00.00" in text
    # 13.0 - 10.0 = 3.0 → rebased to 00:03.00
    assert "00:03.00" in text
    # Block IDs should NOT appear
    assert "E01-B001" not in text
    assert "E01-B002" not in text


def test_format_clip_scene_heading_no_scene_id():
    scenes = [
        {"id": "E01-S01", "heading": "INT. CHURCH – DAY", "start": 0.0, "end": 60.0},
        {"id": "E01-S02", "heading": "EXT. GARDEN – DUSK", "start": 60.0, "end": 120.0},
    ]
    blocks = [
        _bl("E01-B001", "CAMERA", 0.0, 5.0, scene_id="E01-S01"),
        _bl("E01-B002", "CAMERA", 60.0, 65.0, scene_id="E01-S02"),
    ]
    show = _make_show([_ep(1, blocks, scenes=scenes)])
    seg = _seg(1, 0.0, 65.0, "E01-B001", "E01-B002")
    promo = _make_promo("C-E01-01", [seg], "E01-B001", "E01-B002")

    text = format_clip(promo, show)
    # Scene heading text appears
    assert "INT. CHURCH – DAY" in text
    assert "EXT. GARDEN – DUSK" in text
    # Scene ID does NOT appear
    assert "E01-S01" not in text
    assert "E01-S02" not in text


def test_format_clip_two_segments_cut_separator():
    blocks_ep1 = [
        _bl("E01-B001", "DIALOGUE", 0.0, 10.0, "Start", label_raw="ALICE"),
        _bl("E01-B010", "ACTION", 25.0, 30.0, "End ep1"),
    ]
    blocks_ep2 = [
        _bl("E02-B001", "CAMERA", 0.0, 5.0, "Open ep2"),
        _bl("E02-B020", "DIALOGUE", 20.0, 30.0, "Cliff", label_raw="BOB"),
    ]
    show = _make_show([_ep(1, blocks_ep1), _ep(2, blocks_ep2)])
    seg1 = _seg(1, 0.0, 30.0, "E01-B001", "E01-B010")
    seg2 = _seg(2, 0.0, 30.0, "E02-B001", "E02-B020")
    promo = _make_promo("C-E01-01", [seg1, seg2], "E01-B001", "E02-B020")

    text = format_clip(promo, show)
    assert "== CUT ==" in text
    # Times in segment 2 are rebased to continue from segment 1 end (30 s)
    # E02-B001 starts at 0.0 in ep, seg2 starts at 0.0, cum_offset=30.0 → rebased to 30.0
    assert "00:30.00" in text
    # No episode numbers from IDs in content
    assert "E02-B001" not in text


def test_format_clip_no_episode_numbers_in_content():
    """Block IDs like E01-B027 should not appear in format_clip output."""
    blocks = [
        _bl("E01-B027", "DIALOGUE", 5.0, 10.0, "Shocking line", label_raw="GERALD (Cold)"),
    ]
    show = _make_show([_ep(1, blocks)])
    seg = _seg(1, 5.0, 10.0, "E01-B027", "E01-B027")
    promo = _make_promo("C-E01-01", [seg], "E01-B027", "E01-B027")

    text = format_clip(promo, show)
    assert "E01-B027" not in text
    # label_raw should appear
    assert "GERALD (Cold)" in text


# ---------------------------------------------------------------------------
# 6. Batching
# ---------------------------------------------------------------------------

def _make_promos(n: int) -> list[dict]:
    promos = []
    for i in range(n):
        pid = f"C-E01-{i + 1:02d}"
        seg = _seg(1, float(i * 30), float(i * 30 + 25), f"E01-B{i*10+1:03d}", f"E01-B{i*10+9:03d}")
        promos.append(_make_promo(pid, [seg], f"E01-B{i*10+1:03d}", f"E01-B{i*10+9:03d}"))
    return promos


def _fake_llm_response(labels: list[str]) -> dict:
    return {
        "clips": [
            {
                "label": lb, "hook": 3, "cliffhanger": 3, "standalone": 3,
                "confusions": [], "safety": "ok", "safety_reason": "",
                "hook_moment": "nothing", "why": "test",
            }
            for lb in labels
        ]
    }


def test_batching_each_clip_once_per_round():
    """Each clip appears exactly once per round; deterministic."""
    n = 20
    promos = _make_promos(n)
    pids = [p["promo_id"] for p in promos]

    # Round 1
    rng1 = random.Random(1)
    s1 = list(pids)
    rng1.shuffle(s1)
    seen1 = set()
    for pid in s1:
        assert pid not in seen1, "duplicate in round 1"
        seen1.add(pid)
    assert seen1 == set(pids)

    # Round 2 differs from round 1
    rng2 = random.Random(2)
    s2 = list(pids)
    rng2.shuffle(s2)
    assert s1 != s2  # almost certainly different


def test_batching_labels_a_to_h():
    """Batches of 8 use labels A–H; last batch may be smaller."""
    from promo_finder.judge import _BATCH_SIZE, _LABELS
    assert _BATCH_SIZE == 8
    assert _LABELS[:8] == list("ABCDEFGH")


# ---------------------------------------------------------------------------
# 7. Response validation
# ---------------------------------------------------------------------------

def test_validation_missing_label():
    labels = ["A", "B", "C"]
    response = {
        "clips": [
            {"label": "A", "hook": 3, "cliffhanger": 3, "standalone": 3,
             "confusions": [], "safety": "ok", "safety_reason": "", "hook_moment": "x", "why": "x"},
            # B is missing
            {"label": "C", "hook": 4, "cliffhanger": 4, "standalone": 4,
             "confusions": [], "safety": "ok", "safety_reason": "", "hook_moment": "x", "why": "x"},
        ]
    }
    valid = _validate_response(response, labels)
    assert "A" in valid
    assert "B" not in valid
    assert "C" in valid


def test_validation_score_out_of_range():
    labels = ["A"]
    response = {
        "clips": [
            {"label": "A", "hook": 6, "cliffhanger": 3, "standalone": 3,  # 6 is invalid
             "confusions": [], "safety": "ok", "safety_reason": "", "hook_moment": "x", "why": "x"},
        ]
    }
    valid = _validate_response(response, labels)
    assert "A" not in valid


def test_validation_bad_safety():
    labels = ["A"]
    response = {
        "clips": [
            {"label": "A", "hook": 3, "cliffhanger": 3, "standalone": 3,
             "confusions": [], "safety": "maybe", "safety_reason": "",  # invalid safety
             "hook_moment": "x", "why": "x"},
        ]
    }
    valid = _validate_response(response, labels)
    assert "A" not in valid


def test_validation_duplicate_label():
    labels = ["A", "B"]
    response = {
        "clips": [
            {"label": "A", "hook": 3, "cliffhanger": 3, "standalone": 3,
             "confusions": [], "safety": "ok", "safety_reason": "", "hook_moment": "x", "why": "x"},
            {"label": "A", "hook": 4, "cliffhanger": 4, "standalone": 4,  # duplicate
             "confusions": [], "safety": "ok", "safety_reason": "", "hook_moment": "x", "why": "x"},
            {"label": "B", "hook": 2, "cliffhanger": 2, "standalone": 2,
             "confusions": [], "safety": "ok", "safety_reason": "", "hook_moment": "x", "why": "x"},
        ]
    }
    valid = _validate_response(response, labels)
    assert "A" not in valid  # duplicate → invalid
    assert "B" in valid


# ---------------------------------------------------------------------------
# 8. Combining: mean, disagreement, worst safety, single round
# ---------------------------------------------------------------------------

def test_combine_mean_scores():
    blocks = [_bl("E01-B001", "ACTION", 0.0, 30.0)]
    show = _make_show([_ep(1, blocks)])
    seg = _seg(1, 0.0, 30.0, "E01-B001", "E01-B001")
    promo = _make_promo("C-E01-01", [seg], "E01-B001", "E01-B001")

    r1 = {"hook": 3, "cliffhanger": 4, "standalone": 2, "confusions": [],
          "safety": "ok", "safety_reason": "", "hook_moment": "x", "why": "r1 why"}
    r2 = {"hook": 5, "cliffhanger": 2, "standalone": 4, "confusions": [],
          "safety": "ok", "safety_reason": "", "hook_moment": "y", "why": "r2 why"}

    with patch("promo_finder.judge._llm.complete_json") as mock_llm:
        call_count = [0]

        def fake_call(prompt_name, variables, *, tag):
            call_count[0] += 1
            labels = ["A"]  # single promo, batch of 1
            if call_count[0] == 1:
                r = r1
            else:
                r = r2
            return {"clips": [{"label": "A", **r}]}

        mock_llm.side_effect = fake_call

        _, judged = run_judge([promo], show)

    assert len(judged) == 1
    j = judged[0]
    assert j["judge_rounds"] == 2
    assert j["scores"]["hook"] == 4.0       # (3+5)/2
    assert j["scores"]["cliffhanger"] == 3.0  # (4+2)/2
    assert j["scores"]["standalone"] == 3.0  # (2+4)/2
    assert j["judge_disagreement"] == 2  # max of |3-5|=2, |4-2|=2, |2-4|=2
    assert j["why"] == "r1 why"  # from round 1


def test_combine_worst_safety():
    blocks = [_bl("E01-B001", "ACTION", 0.0, 30.0)]
    show = _make_show([_ep(1, blocks)])
    seg = _seg(1, 0.0, 30.0, "E01-B001", "E01-B001")
    promo = _make_promo("C-E01-01", [seg], "E01-B001", "E01-B001")

    call_count = [0]

    def fake_call(prompt_name, variables, *, tag):
        call_count[0] += 1
        level = "sensitive" if call_count[0] == 1 else "ok"
        reason = "violence" if call_count[0] == 1 else ""
        return {"clips": [{"label": "A", "hook": 3, "cliffhanger": 3, "standalone": 3,
                           "confusions": [], "safety": level,
                           "safety_reason": reason, "hook_moment": "x", "why": "y"}]}

    with patch("promo_finder.judge._llm.complete_json", side_effect=fake_call):
        _, judged = run_judge([promo], show)

    assert judged[0]["safety"]["level"] == "sensitive"  # worst of ok/sensitive
    assert judged[0]["safety"]["reason"] == "violence"


def test_combine_single_round():
    """When only 1 round is valid, judge_disagreement is null."""
    blocks = [_bl("E01-B001", "ACTION", 0.0, 30.0)]
    show = _make_show([_ep(1, blocks)])
    seg = _seg(1, 0.0, 30.0, "E01-B001", "E01-B001")
    promo = _make_promo("C-E01-01", [seg], "E01-B001", "E01-B001")

    call_count = [0]

    def fake_call(prompt_name, variables, *, tag):
        call_count[0] += 1
        from promo_finder.judge import _llm
        if call_count[0] == 2:
            raise _llm.LLMError("API error")
        return {"clips": [{"label": "A", "hook": 4, "cliffhanger": 4, "standalone": 4,
                           "confusions": [], "safety": "ok",
                           "safety_reason": "", "hook_moment": "x", "why": "y"}]}

    with patch("promo_finder.judge._llm.complete_json", side_effect=fake_call):
        _, judged = run_judge([promo], show)

    assert judged[0]["judge_rounds"] == 1
    assert judged[0]["judge_disagreement"] is None
    assert judged[0]["scores"]["hook"] == 4.0

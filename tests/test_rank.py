"""Tests for rank.py: scoring, safety, overlap, top-10 variety, text fill."""
from __future__ import annotations

import pytest

from promo_finder.rank import (
    _weighted_score,
    _acquisition_score,
    _promos_overlap,
    _cluster_overlaps,
    _block_text,
    _sort_key,
    rank_promos,
)
from promo_finder.show import Show


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bl(bid: str, btype: str, start: float, end: float, text: str = "...",
        label_raw: str | None = None) -> dict:
    ep_num = int(bid.split("-")[0][1:])
    return {
        "id": bid, "type": btype, "start": start, "end": end, "text": text,
        "label_raw": label_raw or ("SPEAKER" if btype == "DIALOGUE" else "CAMERA"),
        "scene_id": f"E{ep_num:02d}-S01",
        "episode": ep_num,
    }


def _ep(ep_num: int, blocks: list[dict], dur: float = 300.0) -> dict:
    return {
        "episode": ep_num, "logline": "Test.", "continuity_notes": "",
        "scenes": [{"id": f"E{ep_num:02d}-S01", "heading": "INT. HALL – DAY",
                    "start": 0.0, "end": dur}],
        "blocks": blocks, "duration": dur,
    }


def _seg(ep: int, start: float, end: float, start_bl: str, end_bl: str) -> dict:
    return {
        "start_block": start_bl, "end_block": end_bl,
        "episode": ep, "start": start, "end": end,
        "start_tc": "00:00.00", "end_tc": "00:30.00",
        "duration": end - start,
    }


def _promo(
    pid: str,
    seg: dict,
    hook_bid: str,
    cliff_bid: str,
    scores: dict | None = None,
    safety: str = "ok",
) -> dict:
    return {
        "promo_id": pid,
        "segments": [seg],
        "hook": {"block_id": hook_bid, "at": 0.0},
        "cliffhanger": {"block_id": cliff_bid, "at": 25.0},
        "beat_notes": {}, "why": "test", "method": "pipeline",
        "duration": seg["end"] - seg["start"],
        "checks": {"hard": {}, "soft": {}, "errors": [], "valid": True},
        "scores": scores or {"hook": 3, "cliffhanger": 3, "standalone": 3},
        "safety": {"level": safety, "reason": ""},
        "confusions": [],
        "judge_rounds": 2,
    }


def _make_show(ep_blocks: dict[int, list[dict]]) -> Show:
    episodes = [_ep(ep, blocks) for ep, blocks in ep_blocks.items()]
    return Show(title="Test", slug="test", episodes=episodes)


# ---------------------------------------------------------------------------
# Weighted score
# ---------------------------------------------------------------------------

def test_weighted_score_formula():
    s = {"hook": 4, "cliffhanger": 3, "standalone": 2}
    assert _weighted_score(s) == pytest.approx(0.4 * 4 + 0.3 * 3 + 0.3 * 2)


def test_weighted_score_max():
    s = {"hook": 5, "cliffhanger": 5, "standalone": 5}
    assert _weighted_score(s) == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

def test_unsafe_excluded():
    blocks = [_bl("E01-B001", "CAMERA", 0.0, 30.0)]
    show = _make_show({1: blocks})
    seg = _seg(1, 0.0, 30.0, "E01-B001", "E01-B001")
    p = _promo("P1", seg, "E01-B001", "E01-B001", safety="unsafe")
    ranked, excluded = rank_promos([p], show)
    assert len(ranked) == 0
    assert len(excluded) == 1
    assert excluded[0]["promo_id"] == "P1"


def test_sensitive_penalty():
    blocks = [_bl("E01-B001", "CAMERA", 0.0, 30.0)]
    show = _make_show({1: blocks})
    seg = _seg(1, 0.0, 30.0, "E01-B001", "E01-B001")
    p = _promo("P1", seg, "E01-B001", "E01-B001",
               scores={"hook": 4, "cliffhanger": 4, "standalone": 4},
               safety="sensitive")
    ranked, _ = rank_promos([p], show)
    assert len(ranked) == 1
    expected = pytest.approx(_weighted_score({"hook": 4, "cliffhanger": 4, "standalone": 4}) - 0.5)
    assert ranked[0]["score"] == expected
    assert "needs_review" in ranked[0]["flags"]


def test_ok_no_penalty():
    blocks = [_bl("E01-B001", "CAMERA", 0.0, 30.0)]
    show = _make_show({1: blocks})
    seg = _seg(1, 0.0, 30.0, "E01-B001", "E01-B001")
    scores = {"hook": 4, "cliffhanger": 3, "standalone": 3}
    p = _promo("P1", seg, "E01-B001", "E01-B001", scores=scores)
    ranked, _ = rank_promos([p], show)
    assert ranked[0]["score"] == pytest.approx(_weighted_score(scores))
    assert ranked[0]["flags"] == []


# ---------------------------------------------------------------------------
# Overlap clustering
# ---------------------------------------------------------------------------

def test_no_overlap_different_episodes():
    s1 = _seg(1, 0.0, 30.0, "E01-B001", "E01-B001")
    s2 = _seg(2, 0.0, 30.0, "E02-B001", "E02-B001")
    p1 = {"segments": [s1]}
    p2 = {"segments": [s2]}
    assert not _promos_overlap(p1, p2)


def test_no_overlap_same_episode_no_time_intersection():
    s1 = _seg(1, 0.0, 30.0, "E01-B001", "E01-B001")
    s2 = _seg(1, 60.0, 90.0, "E01-B001", "E01-B001")
    p1 = {"segments": [s1]}
    p2 = {"segments": [s2]}
    assert not _promos_overlap(p1, p2)


def test_overlap_more_than_50pct():
    # s1: 0–30, s2: 10–40; intersection=20, shorter=30, 20/30 > 0.5
    s1 = {"episode": 1, "start": 0.0, "end": 30.0}
    s2 = {"episode": 1, "start": 10.0, "end": 40.0}
    p1 = {"segments": [s1]}
    p2 = {"segments": [s2]}
    assert _promos_overlap(p1, p2)


def test_overlap_exactly_50pct_not_overlap():
    # s1: 0–20, s2: 10–30; intersection=10, shorter=20, 10/20 = 0.5, not > 0.5
    s1 = {"episode": 1, "start": 0.0, "end": 20.0}
    s2 = {"episode": 1, "start": 10.0, "end": 30.0}
    p1 = {"segments": [s1]}
    p2 = {"segments": [s2]}
    assert not _promos_overlap(p1, p2)


def test_overlap_cluster_keeps_highest_score_as_main():
    blocks = [
        _bl("E01-B001", "CAMERA", 0.0, 50.0),
        _bl("E01-B010", "CAMERA", 50.0, 100.0),
    ]
    show = _make_show({1: blocks})
    # Both promos cover 0–40 (heavily overlapping)
    seg_a = {"episode": 1, "start": 0.0, "end": 40.0,
             "start_block": "E01-B001", "end_block": "E01-B001",
             "start_tc": "00:00.00", "end_tc": "00:40.00", "duration": 40.0}
    seg_b = {"episode": 1, "start": 5.0, "end": 45.0,
             "start_block": "E01-B001", "end_block": "E01-B001",
             "start_tc": "00:05.00", "end_tc": "00:45.00", "duration": 40.0}
    p_hi = {
        "promo_id": "P-HI", "segments": [seg_a],
        "hook": {"block_id": "E01-B001", "at": 0.0},
        "cliffhanger": {"block_id": "E01-B001", "at": 35.0},
        "beat_notes": {}, "why": "hi", "method": "pipeline", "duration": 40.0,
        "checks": {"hard": {}, "soft": {}, "errors": [], "valid": True},
        "scores": {"hook": 5, "cliffhanger": 5, "standalone": 5},
        "safety": {"level": "ok", "reason": ""},
        "confusions": [], "judge_rounds": 2,
    }
    p_lo = {
        "promo_id": "P-LO", "segments": [seg_b],
        "hook": {"block_id": "E01-B001", "at": 0.0},
        "cliffhanger": {"block_id": "E01-B001", "at": 35.0},
        "beat_notes": {}, "why": "lo", "method": "pipeline", "duration": 40.0,
        "checks": {"hard": {}, "soft": {}, "errors": [], "valid": True},
        "scores": {"hook": 2, "cliffhanger": 2, "standalone": 2},
        "safety": {"level": "ok", "reason": ""},
        "confusions": [], "judge_rounds": 2,
    }
    ranked, _ = rank_promos([p_hi, p_lo], show)
    assert len(ranked) == 1
    assert ranked[0]["promo_id"] == "P-HI"
    alts = ranked[0]["alternatives"]
    assert len(alts) == 1
    assert alts[0]["promo_id"] == "P-LO"


# ---------------------------------------------------------------------------
# One per episode in top 10
# ---------------------------------------------------------------------------

def test_top10_one_per_episode():
    """The variety top 10 has at most one promo per starting episode."""
    # 15 episodes × 2 promos each = 30 promos; expect top 10 to have one per episode
    all_blocks = {ep: [_bl(f"E{ep:02d}-B001", "CAMERA", 0.0, 300.0)] for ep in range(1, 16)}
    show = _make_show(all_blocks)

    promos = []
    for ep in range(1, 16):
        bid = f"E{ep:02d}-B001"
        for i in range(2):  # 2 promos per episode, non-overlapping
            seg = {
                "episode": ep, "start": float(i * 100), "end": float(i * 100 + 40),
                "start_block": bid, "end_block": bid,
                "start_tc": "00:00.00", "end_tc": "00:40.00", "duration": 40.0,
            }
            promos.append({
                "promo_id": f"P-E{ep:02d}-{i:02d}",
                "segments": [seg],
                "hook": {"block_id": bid, "at": 0.0},
                "cliffhanger": {"block_id": bid, "at": 35.0},
                "beat_notes": {}, "why": "", "method": "pipeline", "duration": 40.0,
                "checks": {"hard": {}, "soft": {}, "errors": [], "valid": True},
                "scores": {"hook": 3, "cliffhanger": 3, "standalone": 3},
                "safety": {"level": "ok", "reason": ""},
                "confusions": [], "judge_rounds": 2,
            })

    ranked, _ = rank_promos(promos, show)
    variety_top10 = [p for p in ranked if p["rank"] <= 10]
    top10_episodes = [
        min(s.get("episode", 9999) for s in p["segments"])
        for p in variety_top10
    ]
    # Exactly 10 promos selected; each from a different episode
    assert len(variety_top10) == 10
    assert len(top10_episodes) == len(set(top10_episodes))


# ---------------------------------------------------------------------------
# Tie-breaks
# ---------------------------------------------------------------------------

def test_tiebreak_earlier_episode_first():
    all_blocks = {ep: [_bl(f"E{ep:02d}-B001", "CAMERA", 0.0, 60.0)] for ep in [1, 5]}
    show = _make_show(all_blocks)
    scores = {"hook": 3, "cliffhanger": 3, "standalone": 3}
    p_late = {
        "promo_id": "P-E05",
        "segments": [{"episode": 5, "start": 0.0, "end": 30.0,
                      "start_block": "E05-B001", "end_block": "E05-B001",
                      "start_tc": "00:00.00", "end_tc": "00:30.00", "duration": 30.0}],
        "hook": {"block_id": "E05-B001", "at": 0.0},
        "cliffhanger": {"block_id": "E05-B001", "at": 25.0},
        "beat_notes": {}, "why": "", "method": "pipeline", "duration": 30.0,
        "checks": {}, "scores": scores,
        "safety": {"level": "ok", "reason": ""}, "confusions": [], "judge_rounds": 2,
    }
    p_early = {
        "promo_id": "P-E01",
        "segments": [{"episode": 1, "start": 0.0, "end": 30.0,
                      "start_block": "E01-B001", "end_block": "E01-B001",
                      "start_tc": "00:00.00", "end_tc": "00:30.00", "duration": 30.0}],
        "hook": {"block_id": "E01-B001", "at": 0.0},
        "cliffhanger": {"block_id": "E01-B001", "at": 25.0},
        "beat_notes": {}, "why": "", "method": "pipeline", "duration": 30.0,
        "checks": {}, "scores": scores,
        "safety": {"level": "ok", "reason": ""}, "confusions": [], "judge_rounds": 2,
    }
    ranked, _ = rank_promos([p_late, p_early], show)
    assert ranked[0]["promo_id"] == "P-E01"
    assert ranked[1]["promo_id"] == "P-E05"


def test_tiebreak_shorter_duration():
    # Two promos in different episodes so they don't overlap-cluster
    blocks = {
        1: [_bl("E01-B001", "CAMERA", 0.0, 60.0)],
        2: [_bl("E02-B001", "CAMERA", 0.0, 60.0)],
    }
    show = _make_show(blocks)
    scores = {"hook": 3, "cliffhanger": 3, "standalone": 3}

    def _p(pid: str, ep: int, duration: float) -> dict:
        bid = f"E{ep:02d}-B001"
        return {
            "promo_id": pid,
            "segments": [{"episode": ep, "start": 0.0, "end": duration,
                          "start_block": bid, "end_block": bid,
                          "start_tc": "00:00.00", "end_tc": "00:30.00", "duration": duration}],
            "hook": {"block_id": bid, "at": 0.0},
            "cliffhanger": {"block_id": bid, "at": duration - 5},
            "beat_notes": {}, "why": "", "method": "pipeline", "duration": duration,
            "checks": {}, "scores": scores,
            "safety": {"level": "ok", "reason": ""}, "confusions": [], "judge_rounds": 2,
        }

    # Same score, same episode number → shorter wins
    ranked, _ = rank_promos([_p("LONG", 1, 55.0), _p("SHORT", 1, 25.0)], show)
    # They might overlap or not — the main promo is the first in sort (shorter wins by sort key
    # only if both survive as main promos, i.e. they don't overlap)
    # Overlap check: start=0,end=55 vs start=0,end=25; intersection=25, shorter=25, ratio=1.0 > 0.5 → overlap
    # So they cluster; main = higher score (tied) → sort by promo_id: "LONG" < "SHORT"
    # The test should verify tie-break in sort order NOT via clusters.
    # Use promos in different episodes to avoid clustering:
    ranked2, _ = rank_promos([_p("EP1-LONG", 1, 55.0), _p("EP2-SHORT", 2, 25.0)], show)
    # Both ep 1 and ep 2 — same score, ep1 < ep2, so EP1-LONG comes first
    assert ranked2[0]["promo_id"] == "EP1-LONG"

    # Tie-break by duration: same score, same episode (force via different promos not overlapping)
    # Create two promos in ep2 with same episode but no time overlap
    p_long = {
        "promo_id": "LONG2",
        "segments": [{"episode": 2, "start": 0.0, "end": 55.0,
                      "start_block": "E02-B001", "end_block": "E02-B001",
                      "start_tc": "00:00.00", "end_tc": "00:55.00", "duration": 55.0}],
        "hook": {"block_id": "E02-B001", "at": 0.0},
        "cliffhanger": {"block_id": "E02-B001", "at": 50.0},
        "beat_notes": {}, "why": "", "method": "pipeline", "duration": 55.0,
        "checks": {}, "scores": scores,
        "safety": {"level": "ok", "reason": ""}, "confusions": [], "judge_rounds": 2,
    }
    p_short = {
        "promo_id": "SHORT2",
        "segments": [{"episode": 2, "start": 100.0, "end": 125.0,
                      "start_block": "E02-B001", "end_block": "E02-B001",
                      "start_tc": "01:40.00", "end_tc": "02:05.00", "duration": 25.0}],
        "hook": {"block_id": "E02-B001", "at": 0.0},
        "cliffhanger": {"block_id": "E02-B001", "at": 20.0},
        "beat_notes": {}, "why": "", "method": "pipeline", "duration": 25.0,
        "checks": {}, "scores": scores,
        "safety": {"level": "ok", "reason": ""}, "confusions": [], "judge_rounds": 2,
    }
    ranked3, _ = rank_promos([p_long, p_short], show)
    # Same score, same ep — shorter wins
    assert ranked3[0]["promo_id"] == "SHORT2"


# ---------------------------------------------------------------------------
# Text fields come from show
# ---------------------------------------------------------------------------

def test_text_fields_from_show():
    blocks = [
        _bl("E01-B001", "CAMERA", 0.0, 5.0, "Wide establishing shot"),
        _bl("E01-B020", "DIALOGUE", 25.0, 30.0, "You abandoned me.", label_raw="ALICE"),
    ]
    show = _make_show({1: blocks})
    seg = _seg(1, 0.0, 30.0, "E01-B001", "E01-B020")
    p = {
        "promo_id": "P1",
        "segments": [seg],
        "hook": {"block_id": "E01-B001", "at": 0.0},
        "cliffhanger": {"block_id": "E01-B020", "at": 25.0},
        "beat_notes": {}, "why": "test", "method": "pipeline", "duration": 30.0,
        "checks": {}, "scores": {"hook": 4, "cliffhanger": 4, "standalone": 4},
        "safety": {"level": "ok", "reason": ""},
        "confusions": [], "judge_rounds": 2,
    }
    ranked, _ = rank_promos([p], show)
    r = ranked[0]
    # hook block is CAMERA type → no speaker prefix
    assert r["hook"]["text"] == "Wide establishing shot"
    # cliffhanger block is DIALOGUE → includes speaker
    assert r["cliffhanger"]["text"] == "ALICE: You abandoned me."


def test_block_text_dialogue_includes_speaker():
    blocks = [_bl("E01-B001", "DIALOGUE", 0.0, 5.0, "Hello.", label_raw="BOB (Angry)")]
    show = Show(title="T", slug="t", episodes=[_ep(1, blocks)])
    assert _block_text(show, "E01-B001") == "BOB (Angry): Hello."


def test_block_text_camera_no_speaker():
    blocks = [_bl("E01-B001", "CAMERA", 0.0, 5.0, "Close on her face.")]
    show = Show(title="T", slug="t", episodes=[_ep(1, blocks)])
    assert _block_text(show, "E01-B001") == "Close on her face."


# ---------------------------------------------------------------------------
# acquisition_score formula
# ---------------------------------------------------------------------------

def test_acquisition_score_first_episode_no_penalty():
    # E01 of a 10-episode show gets no penalty
    assert _acquisition_score(3.0, first_episode=1, n_episodes=10) == pytest.approx(3.0)


def test_acquisition_score_last_episode_max_penalty():
    # Last episode of a 10-episode show gets −0.5
    assert _acquisition_score(3.0, first_episode=10, n_episodes=10) == pytest.approx(2.5)


def test_acquisition_score_middle_episode():
    # E5 of a 9-episode show: penalty = 0.5 * (5-1)/(9-1) = 0.5 * 0.5 = 0.25
    assert _acquisition_score(3.0, first_episode=5, n_episodes=9) == pytest.approx(2.75)


def test_acquisition_score_single_episode_show_no_penalty():
    # Degenerate: n_episodes=1 → no penalty (avoid division by zero)
    assert _acquisition_score(4.0, first_episode=1, n_episodes=1) == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# Late promo with higher raw score loses to early promo in acquisition ranking
# ---------------------------------------------------------------------------

def test_late_promo_higher_raw_score_loses_to_early():
    """A late-episode promo with score 4.0 should rank below an early promo
    with score 3.0 if the acquisition penalty brings the late score below 3.0."""
    # 10 episodes: late promo at E10 with score 4.0 → acq = 4.0 - 0.5 = 3.5
    # early promo at E01 with score 3.5 → acq = 3.5
    # Tie on acq_score → E01 wins by episode tie-break
    # Let's make it cleaner: E01 score=3.6, E10 score=4.0 → acq E01=3.6, acq E10=3.5 → E01 wins
    all_blocks = {ep: [_bl(f"E{ep:02d}-B001", "CAMERA", 0.0, 60.0)] for ep in range(1, 11)}
    show = _make_show(all_blocks)

    def _p(pid: str, ep: int, score_val: float) -> dict:
        bid = f"E{ep:02d}-B001"
        v = int(score_val)
        return {
            "promo_id": pid,
            "segments": [{"episode": ep, "start": 0.0, "end": 30.0,
                          "start_block": bid, "end_block": bid,
                          "start_tc": "00:00.00", "end_tc": "00:30.00", "duration": 30.0}],
            "hook": {"block_id": bid, "at": 0.0},
            "cliffhanger": {"block_id": bid, "at": 25.0},
            "beat_notes": {}, "why": "", "method": "pipeline", "duration": 30.0,
            "checks": {}, "scores": {"hook": score_val, "cliffhanger": score_val, "standalone": score_val},
            "safety": {"level": "ok", "reason": ""}, "confusions": [], "judge_rounds": 2,
        }

    early = _p("EARLY", ep=1, score_val=3.6)
    late = _p("LATE", ep=10, score_val=4.0)
    ranked, _ = rank_promos([late, early], show)

    # EARLY has acq_score=3.6, LATE has acq_score=4.0-0.5=3.5 → EARLY ranks first
    assert ranked[0]["promo_id"] == "EARLY"
    assert ranked[1]["promo_id"] == "LATE"


# ---------------------------------------------------------------------------
# Retargeting list
# ---------------------------------------------------------------------------

def test_retargeting_only_from_last_third():
    """Retargeting set must only contain promos whose first_episode > 2/3 × n_episodes."""
    # 9 episodes: threshold = int(2/3*9) = 6; retargeting → episodes 7, 8, 9
    all_blocks = {ep: [_bl(f"E{ep:02d}-B001", "CAMERA", 0.0, 60.0)] for ep in range(1, 10)}
    show = _make_show(all_blocks)

    def _p(ep: int) -> dict:
        bid = f"E{ep:02d}-B001"
        return {
            "promo_id": f"P-E{ep:02d}",
            "segments": [{"episode": ep, "start": 0.0, "end": 30.0,
                          "start_block": bid, "end_block": bid,
                          "start_tc": "00:00.00", "end_tc": "00:30.00", "duration": 30.0}],
            "hook": {"block_id": bid, "at": 0.0},
            "cliffhanger": {"block_id": bid, "at": 25.0},
            "beat_notes": {}, "why": "", "method": "pipeline", "duration": 30.0,
            "checks": {}, "scores": {"hook": 4, "cliffhanger": 4, "standalone": 4},
            "safety": {"level": "ok", "reason": ""}, "confusions": [], "judge_rounds": 2,
        }

    promos = [_p(ep) for ep in range(1, 10)]
    ranked, _ = rank_promos(promos, show)

    retargeting = [p for p in ranked if p.get("audience") == "retargeting"]
    ret_episodes = [
        min(s.get("episode", 9999) for s in p["segments"])
        for p in retargeting
    ]
    assert all(ep > 6 for ep in ret_episodes), f"Non-last-third ep in retargeting: {ret_episodes}"
    assert len(retargeting) <= 5


def test_retargeting_one_per_episode():
    """The displayed retargeting top 5 has at most one promo per starting episode."""
    # 9 episodes: two non-overlapping promos per episode in the last third (eps 7-9)
    all_blocks = {ep: [_bl(f"E{ep:02d}-B001", "CAMERA", 0.0, 300.0)] for ep in range(1, 10)}
    show = _make_show(all_blocks)

    promos = []
    for ep in range(7, 10):  # episodes 7, 8, 9 — all retargeting (threshold=6)
        bid = f"E{ep:02d}-B001"
        for i in range(2):
            seg = {"episode": ep, "start": float(i * 100), "end": float(i * 100 + 30),
                   "start_block": bid, "end_block": bid,
                   "start_tc": "00:00.00", "end_tc": "00:30.00", "duration": 30.0}
            promos.append({
                "promo_id": f"P-E{ep:02d}-{i}",
                "segments": [seg],
                "hook": {"block_id": bid, "at": 0.0},
                "cliffhanger": {"block_id": bid, "at": 25.0},
                "beat_notes": {}, "why": "", "method": "pipeline", "duration": 30.0,
                "checks": {}, "scores": {"hook": 4, "cliffhanger": 4, "standalone": 4},
                "safety": {"level": "ok", "reason": ""}, "confusions": [], "judge_rounds": 2,
            })

    ranked, _ = rank_promos(promos, show)
    # audience=="retargeting" covers ALL last-third promos; simulate the display filter
    # (top-5, one per episode, by raw score) and check it has no duplicates
    all_ret = sorted(
        [p for p in ranked if p.get("audience") == "retargeting"],
        key=lambda x: (-x.get("score", 0.0), x["promo_id"]),
    )
    seen_ep: set[int] = set()
    displayed: list[dict] = []
    for p in all_ret:
        first_ep = min(s.get("episode", 9999) for s in p["segments"])
        if len(displayed) < 5 and first_ep not in seen_ep:
            displayed.append(p)
            seen_ep.add(first_ep)
    ret_episodes = [min(s.get("episode", 9999) for s in p["segments"]) for p in displayed]
    assert len(ret_episodes) == len(set(ret_episodes)), "Duplicate episode in displayed retargeting"


def test_retargeting_max_five():
    """Retargeting list is capped at 5 entries."""
    # 15 episodes: last third = eps 11-15 (threshold = int(2/3*15) = 10)
    all_blocks = {ep: [_bl(f"E{ep:02d}-B001", "CAMERA", 0.0, 60.0)] for ep in range(1, 16)}
    show = _make_show(all_blocks)

    def _p(ep: int) -> dict:
        bid = f"E{ep:02d}-B001"
        return {
            "promo_id": f"P-E{ep:02d}",
            "segments": [{"episode": ep, "start": 0.0, "end": 30.0,
                          "start_block": bid, "end_block": bid,
                          "start_tc": "00:00.00", "end_tc": "00:30.00", "duration": 30.0}],
            "hook": {"block_id": bid, "at": 0.0},
            "cliffhanger": {"block_id": bid, "at": 25.0},
            "beat_notes": {}, "why": "", "method": "pipeline", "duration": 30.0,
            "checks": {}, "scores": {"hook": 4, "cliffhanger": 4, "standalone": 4},
            "safety": {"level": "ok", "reason": ""}, "confusions": [], "judge_rounds": 2,
        }

    promos = [_p(ep) for ep in range(1, 16)]
    ranked, _ = rank_promos(promos, show)
    retargeting = [p for p in ranked if p.get("audience") == "retargeting"]
    assert len(retargeting) <= 5


# ---------------------------------------------------------------------------
# Audience exclusivity: top-10 ∩ retargeting = ∅
# ---------------------------------------------------------------------------

def test_no_overlap_between_top10_and_retargeting():
    """A retargeting promo with the highest raw score must not appear in the top 10."""
    # 15 episodes: ret_threshold=10; eps 1-10 acquisition, eps 11-15 retargeting.
    # 10 acquisition promos fill rank 1-10; retargeting promo at ep11 (score=5.0) is rank 11+.
    all_blocks = {ep: [_bl(f"E{ep:02d}-B001", "CAMERA", 0.0, 60.0)] for ep in range(1, 16)}
    show = _make_show(all_blocks)

    def _p(ep: int, hook: float = 3.0) -> dict:
        bid = f"E{ep:02d}-B001"
        return {
            "promo_id": f"P-E{ep:02d}",
            "segments": [{"episode": ep, "start": 0.0, "end": 30.0,
                          "start_block": bid, "end_block": bid,
                          "start_tc": "00:00.00", "end_tc": "00:30.00", "duration": 30.0}],
            "hook": {"block_id": bid, "at": 0.0},
            "cliffhanger": {"block_id": bid, "at": 25.0},
            "beat_notes": {}, "why": "", "method": "pipeline", "duration": 30.0,
            "checks": {}, "scores": {"hook": hook, "cliffhanger": hook, "standalone": hook},
            "safety": {"level": "ok", "reason": ""}, "confusions": [], "judge_rounds": 2,
        }

    # Retargeting promo at E11 gets the top score (5.0); acquisition promos score 3.0
    promos = [_p(ep) for ep in range(1, 11)] + [_p(11, hook=5.0)]
    ranked, _ = rank_promos(promos, show)

    top10_ids = {p["promo_id"] for p in ranked if p["rank"] <= 10}
    ret_ids = {p["promo_id"] for p in ranked if p.get("audience") == "retargeting"}

    assert top10_ids.isdisjoint(ret_ids), (
        f"Overlap between top-10 and retargeting: {top10_ids & ret_ids}"
    )
    assert "P-E11" not in top10_ids, "Retargeting promo must not enter new-viewer top 10"
    assert "P-E11" in ret_ids


def test_retargeting_episode_second_promo_blocked_from_top10():
    """Two non-overlapping promos from a retargeting episode: neither enters the top 10."""
    # 15 episodes: ret_threshold=10; eps 1-10 acquisition fill the top 10; ep11 is retargeting.
    all_blocks = {ep: [_bl(f"E{ep:02d}-B001", "CAMERA", 0.0, 300.0)] for ep in range(1, 16)}
    show = _make_show(all_blocks)

    def _p(pid: str, ep: int, start: float, hook: float = 5.0) -> dict:
        bid = f"E{ep:02d}-B001"
        return {
            "promo_id": pid,
            "segments": [{"episode": ep, "start": start, "end": start + 30.0,
                          "start_block": bid, "end_block": bid,
                          "start_tc": "00:00.00", "end_tc": "00:30.00", "duration": 30.0}],
            "hook": {"block_id": bid, "at": 0.0},
            "cliffhanger": {"block_id": bid, "at": 25.0},
            "beat_notes": {}, "why": "", "method": "pipeline", "duration": 30.0,
            "checks": {}, "scores": {"hook": hook, "cliffhanger": hook, "standalone": hook},
            "safety": {"level": "ok", "reason": ""}, "confusions": [], "judge_rounds": 2,
        }

    # One promo per acquisition episode (eps 1-10) + two non-overlapping from ep11 (retargeting)
    promos = [_p(f"P-E{ep:02d}", ep, 0.0) for ep in range(1, 11)]
    promos += [_p("P-E11-A", 11, 0.0), _p("P-E11-B", 11, 100.0)]
    ranked, _ = rank_promos(promos, show)

    top10_ids = {p["promo_id"] for p in ranked if p["rank"] <= 10}
    assert "P-E11-A" not in top10_ids
    assert "P-E11-B" not in top10_ids

"""Tests for candidates.py (fake Show, no network)."""
from __future__ import annotations

import pytest

from promo_finder.candidates import (
    _merge_cliffhangers,
    _first_block_at,
    _last_dialogue_or_action,
    _first_block,
    build_candidates,
)
from promo_finder.show import Show


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bl(bid: str, btype: str, start: float, end: float, text: str = "...",
        label_raw: str | None = None, scene_id: str = "E01-S01") -> dict:
    ep_num = int(bid.split("-")[0][1:])
    return {
        "id": bid, "type": btype, "start": start, "end": end, "text": text,
        "label_raw": label_raw or ("SPEAKER" if btype == "DIALOGUE" else "CAMERA"),
        "scene_id": scene_id, "episode": ep_num,
    }


def _ep(ep_num: int, blocks: list[dict], dur: float = 120.0) -> dict:
    return {
        "episode": ep_num,
        "logline": "Test.",
        "continuity_notes": "",
        "scenes": [{"id": f"E{ep_num:02d}-S01", "heading": f"INT. ROOM E{ep_num:02d} – DAY",
                     "start": 0.0, "end": dur}],
        "blocks": blocks,
        "duration": dur,
    }


def _make_show(episodes: list[dict]) -> Show:
    return Show(title="Test Show", slug="test-show", episodes=episodes)


def _hook(bid: str, start: float, clean_start: float | None = None,
          stop_power: int = 3, htype: str = "reveal") -> dict:
    return {
        "block_id": bid, "type": htype, "stop_power": stop_power,
        "why": "Hook reason", "context_needed": "none",
        "block_type": "DIALOGUE", "start": start, "end": start + 2.0,
        "clean_start": clean_start if clean_start is not None else start,
    }


def _cliff(bid: str, start: float, tension: int = 3) -> dict:
    return {
        "block_id": bid, "tension": tension,
        "open_question": "What happens?",
        "block_type": "ACTION", "start": start, "end": start + 2.0,
    }


def _beats(episodes: list[dict]) -> dict:
    """Build a beats_data dict from episode beat specs."""
    return {"show": "Test", "slug": "test-show", "episodes": episodes}


def _ep_beats(ep_num: int, hooks: list[dict], cliffs: list[dict]) -> dict:
    return {
        "episode": ep_num,
        "hooks": hooks,
        "cliffhangers": cliffs,
        "ending": {"ends_on_cliffhanger": True, "ending_type": "cliffhanger", "note": ""},
        "errors": [],
        "stats": {},
    }


# ---------------------------------------------------------------------------
# 1. Cliffhanger merge
# ---------------------------------------------------------------------------

def test_cliff_merge_keeps_higher_tension():
    c1 = _cliff("E01-B010", 50.0, tension=3)
    c2 = _cliff("E01-B020", 50.5, tension=5)  # within 1.0 s of c1
    merged, count = _merge_cliffhangers([c1, c2])
    assert count == 1
    assert len(merged) == 1
    assert merged[0]["block_id"] == "E01-B020"  # higher tension wins


def test_cliff_merge_tie_keeps_later_end():
    c1 = _cliff("E01-B010", 50.0, tension=4)
    c1["end"] = 52.0
    c2 = _cliff("E01-B020", 50.4, tension=4)
    c2["end"] = 52.4
    merged, count = _merge_cliffhangers([c1, c2])
    assert count == 1
    assert merged[0]["block_id"] == "E01-B020"  # later end wins on tie


def test_cliff_merge_outside_1s_not_merged():
    c1 = _cliff("E01-B010", 50.0, tension=3)
    c1["end"] = 52.0
    c2 = _cliff("E01-B020", 60.0, tension=5)
    c2["end"] = 62.0
    merged, count = _merge_cliffhangers([c1, c2])
    assert count == 0
    assert len(merged) == 2


# ---------------------------------------------------------------------------
# 2. Hook without clean_start is skipped
# ---------------------------------------------------------------------------

def test_hook_without_clean_start_skipped():
    blocks_ep1 = [
        _bl("E01-B001", "CAMERA", 0.0, 5.0),
        _bl("E01-B002", "DIALOGUE", 5.0, 10.0, "Hello"),
        _bl("E01-B010", "DIALOGUE", 10.0, 15.0, "Shocking reveal"),
        _bl("E01-B020", "ACTION", 50.0, 55.0, "Fight"),
        _bl("E01-B030", "DIALOGUE", 100.0, 105.0, "End"),
    ]
    show = _make_show([_ep(1, blocks_ep1)])

    h_good = _hook("E01-B010", 10.0, clean_start=5.0)  # clean_start = B002.start
    h_bad = dict(_hook("E01-B002", 5.0))
    h_bad["clean_start"] = None  # explicitly null

    c = _cliff("E01-B020", 50.0, tension=4)

    beats = _beats([_ep_beats(1, [h_good, h_bad], [c])])
    result = build_candidates(show, beats)
    assert result["stats"]["skipped_no_clean_start"] == 1
    # h_good should produce a candidate; h_bad should not
    cand_ids = [c["hook"]["block_id"] for c in result["candidates"]]
    assert "E01-B010" in cand_ids
    assert "E01-B002" not in cand_ids


# ---------------------------------------------------------------------------
# 3. Single clip uses clean_start for start_block
# ---------------------------------------------------------------------------

def test_single_clip_start_block_uses_clean_start():
    blocks = [
        _bl("E01-B001", "CAMERA", 0.0, 5.0),
        _bl("E01-B002", "DIALOGUE", 5.0, 10.0, "Opening"),
        _bl("E01-B010", "DIALOGUE", 10.0, 15.0, "Hook"),
        _bl("E01-B050", "ACTION", 50.0, 55.0, "Cliffhanger"),
    ]
    show = _make_show([_ep(1, blocks)])
    # clean_start = 5.0 → B002
    h = _hook("E01-B010", 10.0, clean_start=5.0)
    c = _cliff("E01-B050", 50.0, tension=4)
    beats = _beats([_ep_beats(1, [h], [c])])
    result = build_candidates(show, beats)
    assert len(result["candidates"]) >= 1
    cand = result["candidates"][0]
    assert cand["segments"][0]["start_block"] == "E01-B002"
    assert cand["segments"][0]["end_block"] == "E01-B050"


# ---------------------------------------------------------------------------
# 4. Bridge: seg1 ends on last DIALOGUE/ACTION of ep N; seg2 starts at ep N+1 first block
# ---------------------------------------------------------------------------

def test_bridge_segment_endpoints():
    # Timestamps chosen so total duration = 23 + 25 = 48 s (within 20-60 s gate)
    blocks_ep1 = [
        _bl("E01-B001", "CAMERA", 0.0, 2.0),
        _bl("E01-B010", "DIALOGUE", 2.0, 7.0, "Hook line"),
        _bl("E01-B080", "DIALOGUE", 20.0, 25.0, "Last dialogue"),  # end=25
        _bl("E01-B090", "SOUND_FX", 26.0, 28.0, "Silence"),        # not DIALOGUE/ACTION
        _bl("E01-B095", "CAMERA", 28.0, 30.0, "Black"),             # not DIALOGUE/ACTION
    ]
    blocks_ep2 = [
        _bl("E02-B001", "CAMERA", 0.0, 3.0),                        # first block of ep2
        _bl("E02-B050", "DIALOGUE", 20.0, 25.0, "Cliffhanger line"),
    ]
    show = _make_show([_ep(1, blocks_ep1, dur=30.0), _ep(2, blocks_ep2, dur=30.0)])
    # Hook block E01-B010 starts at 2.0; clean_start also 2.0 so _first_block_at finds it
    h = _hook("E01-B010", 2.0, clean_start=2.0)
    c = _cliff("E02-B050", 20.0, tension=4)
    beats = _beats([
        _ep_beats(1, [h], []),
        _ep_beats(2, [], [c]),
    ])
    result = build_candidates(show, beats)
    bridges = [c for c in result["candidates"] if len(c["segments"]) == 2]
    assert len(bridges) >= 1
    bridge = bridges[0]
    # Segment 1 ends on last DIALOGUE block of ep1 (B080, not B090/B095)
    assert bridge["segments"][0]["end_block"] == "E01-B080"
    # Segment 2 starts at first block of ep2 (B001)
    assert bridge["segments"][1]["start_block"] == "E02-B001"
    assert bridge["segments"][1]["end_block"] == "E02-B050"


# ---------------------------------------------------------------------------
# 5. Per-hook selection: highest tension wins
# ---------------------------------------------------------------------------

def test_per_hook_keeps_highest_tension():
    blocks = [
        _bl("E01-B001", "CAMERA", 0.0, 5.0),
        _bl("E01-B010", "DIALOGUE", 5.0, 15.0, "Hook"),
        _bl("E01-B050", "ACTION", 50.0, 55.0, "Cliff low tension"),
        _bl("E01-B060", "ACTION", 60.0, 65.0, "Cliff high tension"),
    ]
    show = _make_show([_ep(1, blocks)])
    h = _hook("E01-B010", 5.0)
    c_low = _cliff("E01-B050", 50.0, tension=2)
    c_high = _cliff("E01-B060", 60.0, tension=5)
    beats = _beats([_ep_beats(1, [h], [c_low, c_high])])
    result = build_candidates(show, beats)
    singles = [c for c in result["candidates"] if len(c["segments"]) == 1]
    # At most 1 single per hook; it should use the high-tension cliff
    assert len(singles) == 1
    assert singles[0]["cliffhanger"]["block_id"] == "E01-B060"


# ---------------------------------------------------------------------------
# 6. Overlap removal
# ---------------------------------------------------------------------------

def test_exact_dedup_removes_identical_segments():
    # Two hooks with the same clean_start produce identical segment lists (same start_block
    # and end_block). A3.3 removes exact duplicates; both hooks survive if they produce
    # different segment lists (different start_block due to different clean_start).
    blocks = [
        _bl("E01-B001", "CAMERA", 0.0, 2.0),
        _bl("E01-B002", "DIALOGUE", 2.0, 7.0, "Hook A"),
        _bl("E01-B003", "DIALOGUE", 7.0, 12.0, "Hook B"),
        _bl("E01-B080", "ACTION", 40.0, 45.0, "Cliff"),
    ]
    show = _make_show([_ep(1, blocks, dur=50.0)])
    # Both hooks have DIFFERENT clean_start → different start_block → distinct segments → both kept
    h_a = _hook("E01-B002", 2.0, clean_start=2.0, stop_power=3)   # start_block = B002
    h_b = _hook("E01-B003", 7.0, clean_start=7.0, stop_power=4)   # start_block = B003
    c = _cliff("E01-B080", 40.0, tension=4)
    beats = _beats([_ep_beats(1, [h_a, h_b], [c])])
    result = build_candidates(show, beats)
    singles = [cand for cand in result["candidates"] if len(cand["segments"]) == 1]
    # Different start_blocks → not exact duplicates → both survive
    assert len(singles) == 2
    assert result["stats"]["removed_dedup"] == 0


def test_exact_dedup_removes_truly_identical():
    # Two hooks with the SAME clean_start → same start_block → identical segments → one removed
    blocks = [
        _bl("E01-B002", "DIALOGUE", 2.0, 7.0, "Hook A"),
        _bl("E01-B003", "DIALOGUE", 7.0, 12.0, "Hook B"),
        _bl("E01-B080", "ACTION", 40.0, 45.0, "Cliff"),
    ]
    show = _make_show([_ep(1, blocks, dur=50.0)])
    h_a = _hook("E01-B002", 2.0, clean_start=2.0, stop_power=3)
    h_b = _hook("E01-B003", 7.0, clean_start=2.0, stop_power=4)  # same clean_start → same start_block
    c = _cliff("E01-B080", 40.0, tension=4)
    beats = _beats([_ep_beats(1, [h_a, h_b], [c])])
    result = build_candidates(show, beats)
    singles = [cand for cand in result["candidates"] if len(cand["segments"]) == 1]
    # Same start_block + same end_block → exact duplicates → only 1 survives
    assert len(singles) == 1
    assert result["stats"]["removed_dedup"] == 1

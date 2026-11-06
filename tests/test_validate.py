"""Tests for the promo validator (task 02)."""
import pytest
from pathlib import Path

from promo_finder.parse import parse_episode
from promo_finder.show import Show
from promo_finder.promo import resolve
from promo_finder.validate import validate

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def show():
    ep, _ = parse_episode(FIXTURES / "ep_promo.txt")
    return Show(title="Test", slug="test", episodes=[ep])


def _promo(start_block, end_block, hook=None, cliffhanger=None, segments=None):
    """Build a minimal raw promo dict."""
    if segments is None:
        segments = [{"start_block": start_block, "end_block": end_block}]
    return {
        "promo_id": "TEST-001",
        "method": "test",
        "segments": segments,
        "hook": hook,
        "cliffhanger": cliffhanger,
        "why": "test",
        "scores": {},
        "rank": None,
    }


def _run(promo_raw, show):
    resolved = resolve(promo_raw, show)
    checks = validate(resolved, show)
    resolved["checks"] = checks
    return resolved


# ---------------------------------------------------------------------------
# 1. Correct single-segment promo: valid, correct start/end/duration
# ---------------------------------------------------------------------------

def test_valid_single_segment(show):
    # B003 (ACTION 00:08.00-00:12.00) → B009 (ACTION 00:40.00-00:46.00) = 38 s
    p = _run(_promo("E02-B003", "E02-B009"), show)
    assert p["checks"]["valid"] is True
    assert p["segments"][0]["start"] == pytest.approx(8.0)
    assert p["segments"][0]["end"] == pytest.approx(46.0)
    assert p["duration"] == pytest.approx(38.0)
    assert p["segments"][0]["start_tc"] == "00:08.00"
    assert p["segments"][0]["end_tc"] == "00:46.00"


# ---------------------------------------------------------------------------
# 2. Cut mid-dialogue: no_mid_line_cut fails
# ---------------------------------------------------------------------------

def test_mid_line_cut(show):
    # B013 starts at 00:05.00, which falls inside ANNA B002 (00:03-00:08)
    p = _run(_promo("E02-B013", "E02-B012"), show)
    assert p["checks"]["hard"]["no_mid_line_cut"] is False
    assert p["checks"]["valid"] is False


# ---------------------------------------------------------------------------
# 3. Duration out of range: duration_20_60 fails
# ---------------------------------------------------------------------------

def test_too_short(show):
    # B008 (00:33.00) → B009 end (00:46.00) = 13 s
    p = _run(_promo("E02-B008", "E02-B009"), show)
    assert p["checks"]["hard"]["duration_20_60"] is False
    assert p["checks"]["valid"] is False


def test_too_long(show):
    # B001 (00:00.00) → B012 end (01:05.00) = 65 s
    p = _run(_promo("E02-B001", "E02-B012"), show)
    assert p["checks"]["hard"]["duration_20_60"] is False
    assert p["checks"]["valid"] is False


# ---------------------------------------------------------------------------
# 4. Unknown block ID: ids_exist fails, no crash
# ---------------------------------------------------------------------------

def test_unknown_block_id(show):
    p = _run(_promo("E02-B999", "E02-B012"), show)
    assert p["checks"]["hard"]["ids_exist"] is False
    assert p["checks"]["valid"] is False
    assert any("E02-B999" in e for e in p["checks"]["errors"])


# ---------------------------------------------------------------------------
# 5. Hook block outside segments: hook_inside fails
# ---------------------------------------------------------------------------

def test_hook_outside_segment(show):
    # Promo is B003-B009 (00:08-00:46); hook is B001 (00:00-00:03), before segment
    hook = {"block_id": "E02-B001", "text": "Wide on the empty hall."}
    p = _run(_promo("E02-B003", "E02-B009", hook=hook), show)
    assert p["checks"]["hard"]["hook_inside"] is False
    assert p["checks"]["valid"] is False


# ---------------------------------------------------------------------------
# 6. Two segments: hook in second segment has correct at offset
# ---------------------------------------------------------------------------

def test_two_segments_hook_at(show):
    # Seg1: B001 (00:00.00) → B003 end (00:12.00), dur = 12.0 s
    # Seg2: B009 (00:40.00) → B011 end (00:58.00), dur = 18.0 s
    # Total = 30.0 s
    # Hook = B010 (DIALOGUE 00:46.00-00:52.00), in seg2
    # at = 12.0 + (46.0 - 40.0) = 18.0 s
    segments = [
        {"start_block": "E02-B001", "end_block": "E02-B003"},
        {"start_block": "E02-B009", "end_block": "E02-B011"},
    ]
    hook = {"block_id": "E02-B010", "text": "Answer me."}
    p = _run(_promo(None, None, hook=hook, segments=segments), show)
    assert p["checks"]["valid"] is True
    assert p["duration"] == pytest.approx(30.0)
    assert p["hook"]["at"] == pytest.approx(18.0)


# ---------------------------------------------------------------------------
# 7. Overlapping segments of same episode: no_overlap fails
# ---------------------------------------------------------------------------

def test_overlapping_segments(show):
    # Seg1: B003 (00:08.00) → B005 end (00:22.00)
    # Seg2: B004 (00:12.00) → B007 end (00:33.00)
    # Seg1 end (22.0) > Seg2 start (12.0) → overlap
    segments = [
        {"start_block": "E02-B003", "end_block": "E02-B005"},
        {"start_block": "E02-B004", "end_block": "E02-B007"},
    ]
    p = _run(_promo(None, None, segments=segments), show)
    assert p["checks"]["hard"]["no_overlap"] is False
    assert p["checks"]["valid"] is False

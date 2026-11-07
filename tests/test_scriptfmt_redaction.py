"""Part 0: test that format_clip redacts all cliffhanger references."""
from __future__ import annotations

import re

import pytest

from promo_finder.scriptfmt import format_clip
from promo_finder.show import Show


def _bl(bid: str, btype: str, start: float, end: float, text: str = "...",
        label_raw: str | None = None) -> dict:
    ep_num = int(bid.split("-")[0][1:])
    return {
        "id": bid, "type": btype, "start": start, "end": end, "text": text,
        "label_raw": label_raw or ("SPEAKER" if btype == "DIALOGUE" else "CAMERA"),
        "scene_id": f"E{ep_num:02d}-S01",
        "episode": ep_num,
    }


def _ep(ep_num: int, blocks: list[dict], dur: float = 120.0) -> dict:
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


def _promo(pid: str, seg: dict, hook_bid: str, cliff_bid: str) -> dict:
    return {
        "promo_id": pid, "segments": [seg],
        "hook": {"block_id": hook_bid, "at": 0.0},
        "cliffhanger": {"block_id": cliff_bid, "at": 25.0},
        "beat_notes": {}, "why": "", "method": "pipeline",
        "duration": seg["end"] - seg["start"],
        "checks": {"hard": {}, "soft": {}, "errors": [], "valid": True},
    }


_CLIFFHANGER_PATTERN = re.compile(r"cliff-?hangers?", re.IGNORECASE)


@pytest.mark.parametrize("text", [
    "cutting to an intense cliffhanger",
    "this is a heart-stopping Cliffhanger moment",
    "the door cracks open—cutting to an intense, heart-stopping cliffhanger.",
    "building to multiple cliffhangers",
    "ends on a cliff-hanger",
    "cliff-hangers keep viewers hooked",
])
def test_format_clip_no_cliffhanger_in_output(text: str):
    blocks = [_bl("E01-B001", "CAMERA", 0.0, 30.0, text)]
    show = Show(title="T", slug="t", episodes=[_ep(1, blocks)])
    seg = _seg(1, 0.0, 30.0, "E01-B001", "E01-B001")
    promo = _promo("C-E01-01", seg, "E01-B001", "E01-B001")

    result = format_clip(promo, show)

    assert not _CLIFFHANGER_PATTERN.search(result), (
        f"format_clip output still contains a cliffhanger match: {result!r}"
    )
    assert "moment" in result


def test_format_clip_redaction_does_not_touch_other_words():
    blocks = [_bl("E01-B001", "CAMERA", 0.0, 10.0, "She looks up at the cliff, hanging on.")]
    show = Show(title="T", slug="t", episodes=[_ep(1, blocks)])
    seg = _seg(1, 0.0, 10.0, "E01-B001", "E01-B001")
    promo = _promo("C-E01-01", seg, "E01-B001", "E01-B001")

    result = format_clip(promo, show)
    # "cliff, hanging" is two words, not "cliffhanger", so it must be preserved
    assert "cliff, hanging" in result

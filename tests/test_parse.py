"""Tests for the screenplay parser (task 01)."""
import pytest
from pathlib import Path

from promo_finder.timeutil import fmt_time, parse_time
from promo_finder.parse import parse_episode, parse_label

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# 1. parse_time / fmt_time round-trip
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "s,expected_secs",
    [
        ("01:12.50", 72.5),
        ("00:00.00", 0.0),
        ("02:18.00", 138.0),
        ("00:09.85", 9.85),
    ],
)
def test_parse_time(s, expected_secs):
    assert parse_time(s) == pytest.approx(expected_secs)


@pytest.mark.parametrize(
    "s",
    ["01:12.50", "00:00.00", "02:18.00", "00:09.85"],
)
def test_fmt_time_roundtrip(s):
    assert fmt_time(parse_time(s)) == s


# ---------------------------------------------------------------------------
# 2. IDs are unique and sequential; scene_id references an existing scene
# ---------------------------------------------------------------------------

def test_ids_unique_and_sequential():
    ep, _ = parse_episode(FIXTURES / "ep_normal.txt")
    scene_ids = {sc["id"] for sc in ep["scenes"]}
    block_ids = {bl["id"] for bl in ep["blocks"]}

    assert len(scene_ids) == len(ep["scenes"]), "Duplicate scene IDs"
    assert len(block_ids) == len(ep["blocks"]), "Duplicate block IDs"

    for i, sc in enumerate(ep["scenes"], 1):
        assert sc["id"] == f"E01-S{i:02d}"
    for i, bl in enumerate(ep["blocks"], 1):
        assert bl["id"] == f"E01-B{i:03d}"

    for bl in ep["blocks"]:
        assert bl["scene_id"] in scene_ids, (
            f"Block {bl['id']} references unknown scene {bl['scene_id']!r}"
        )


# ---------------------------------------------------------------------------
# 3. Uppercase headers parse identically to lowercase
# ---------------------------------------------------------------------------

def test_uppercase_headers_parsed():
    ep, warns = parse_episode(FIXTURES / "ep_upper.txt")
    assert len(ep["scenes"]) == 1
    assert ep["scenes"][0]["heading"] == "EXT. GARDEN – NIGHT"
    assert ep["scenes"][0]["start"] == pytest.approx(0.0)
    assert ep["scenes"][0]["end"] == pytest.approx(45.0)

    types = {bl["type"] for bl in ep["blocks"]}
    assert "CAMERA" in types
    assert "DIALOGUE" in types


# ---------------------------------------------------------------------------
# 4. Dialogue: speaker, delivery, quote-stripping
# ---------------------------------------------------------------------------

def test_dialogue_fields():
    ep, _ = parse_episode(FIXTURES / "ep_normal.txt")

    scholar = next(bl for bl in ep["blocks"] if bl.get("speaker") == "SCHOLAR")
    assert scholar["type"] == "DIALOGUE"
    assert scholar["delivery"] == ["Curious", "Eager"]
    assert scholar["text"] == "What is this place?"

    librarian = next(bl for bl in ep["blocks"] if bl.get("speaker") == "LIBRARIAN")
    assert librarian["type"] == "DIALOGUE"
    assert librarian["delivery"] == []
    assert librarian["text"] == "Welcome."


def test_dialogue_stage_direction_stripped_from_delivery():
    # Verify parse_label handles O.S. / V.O. annotations correctly.
    btype, speaker, delivery = parse_label("MATRIARCH (O.S.) (Firm)")
    assert btype == "DIALOGUE"
    assert speaker == "MATRIARCH"
    assert delivery == ["Firm"]

    btype2, speaker2, delivery2 = parse_label("JULIANA (V.O.) (Reflective, Vulnerable)")
    assert btype2 == "DIALOGUE"
    assert speaker2 == "JULIANA"
    assert delivery2 == ["Reflective", "Vulnerable"]

    btype3, speaker3, delivery3 = parse_label("JULIANA (V.O.)")
    assert btype3 == "DIALOGUE"
    assert speaker3 == "JULIANA"
    assert delivery3 == []

    btype4, speaker4, delivery4 = parse_label("HIGH PRIEST (O.S. / Low, Threatening)")
    assert btype4 == "DIALOGUE"
    assert speaker4 == "HIGH PRIEST"
    assert delivery4 == ["Low", "Threatening"]


# ---------------------------------------------------------------------------
# 5. Unknown label → type OTHER + warning (no crash)
# ---------------------------------------------------------------------------

def test_unknown_label_becomes_other_with_warning():
    ep, warns = parse_episode(FIXTURES / "ep_upper.txt")

    other_blocks = [bl for bl in ep["blocks"] if bl["type"] == "OTHER"]
    assert len(other_blocks) == 1
    assert other_blocks[0]["label_raw"] == "(Whispers)"
    assert other_blocks[0]["speaker"] is None

    assert any("Unknown label" in w for w in warns), (
        f"Expected 'Unknown label' warning, got: {warns}"
    )


# ---------------------------------------------------------------------------
# 6. Unconsumed-line count is 0 for the fixtures
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fname", ["ep_normal.txt", "ep_upper.txt"])
def test_no_unconsumed_lines(fname):
    ep, warns = parse_episode(FIXTURES / fname)
    unconsumed = [w for w in warns if "unconsumed" in w.lower()]
    assert unconsumed == [], f"{fname} has unconsumed lines: {unconsumed}"

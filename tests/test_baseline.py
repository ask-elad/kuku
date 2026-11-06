"""Tests for the dumb baseline (task 02)."""
import json
import pytest
from pathlib import Path

from promo_finder.parse import parse_episode
from promo_finder.show import Show
from promo_finder.baseline import generate_baseline

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def show():
    ep, _ = parse_episode(FIXTURES / "ep_promo.txt")
    return Show(title="Test", slug="test", episodes=[ep])


@pytest.fixture(scope="module")
def baseline_promos(show):
    return generate_baseline(show)


# ---------------------------------------------------------------------------
# 8. Baseline on fixtures
# ---------------------------------------------------------------------------

def test_baseline_produces_promo(baseline_promos):
    # ep_promo.txt has 65 s of blocks; baseline should find a valid ~45 s window
    assert len(baseline_promos) == 1


def test_baseline_promo_valid(baseline_promos):
    p = baseline_promos[0]
    assert p["checks"]["valid"] is True, p["checks"]["errors"]


def test_baseline_no_mid_line_cut(baseline_promos):
    p = baseline_promos[0]
    assert p["checks"]["hard"]["no_mid_line_cut"] is True


def test_baseline_duration_in_range(baseline_promos):
    p = baseline_promos[0]
    assert 20.0 <= p["duration"] <= 60.0


def test_baseline_deterministic(show):
    run1 = generate_baseline(show)
    run2 = generate_baseline(show)
    assert json.dumps(run1) == json.dumps(run2)


def test_baseline_promo_id(baseline_promos):
    assert baseline_promos[0]["promo_id"] == "BASE-E02"


def test_baseline_method(baseline_promos):
    assert baseline_promos[0]["method"] == "baseline"

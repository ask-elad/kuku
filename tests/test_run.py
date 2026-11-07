"""Tests for run.py: stage order and --no-baseline flag."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


def _capture_stages(show_dir: str, extra_args: list[str] | None = None) -> list[str]:
    """Run main() with stubbed _run_stage, return list of stage names executed."""
    extra_args = extra_args or []
    stages_called: list[str] = []

    def fake_run_stage(name: str, cmd: list[str]) -> None:
        stages_called.append(name)

    def fake_load_show(path):
        m = MagicMock()
        m.slug = "test-slug"
        return m

    # Provide a fake LOG_PATH that doesn't exist
    fake_log_path = MagicMock()
    fake_log_path.exists.return_value = False

    with (
        patch("promo_finder.run._run_stage", side_effect=fake_run_stage),
        patch("promo_finder.run.load_show", fake_load_show),
        patch("promo_finder.run._llm._LOG_PATH", fake_log_path),
        patch("sys.argv", ["run", show_dir] + extra_args),
    ):
        from promo_finder.run import main
        main()

    return stages_called


def test_full_run_stage_order():
    stages = _capture_stages("/fake/show")
    expected = ["parse", "baseline", "beats", "candidates", "judge", "calibrate", "rank"]
    assert stages == expected


def test_no_baseline_skips_baseline_stages():
    stages = _capture_stages("/fake/show", ["--no-baseline"])
    assert "baseline" not in stages
    assert "calibrate" not in stages
    # Core stages still present
    assert "parse" in stages
    assert "beats" in stages
    assert "candidates" in stages
    assert "judge" in stages
    assert "rank" in stages


def test_no_baseline_stage_order():
    stages = _capture_stages("/fake/show", ["--no-baseline"])
    core = [s for s in stages if s in ("parse", "beats", "candidates", "judge", "rank")]
    assert core == ["parse", "beats", "candidates", "judge", "rank"]

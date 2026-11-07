"""Eval checks for beats output.

CLI: python -m promo_finder.eval_beats "<show folder>"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .timeutil import fmt_time

_REPO_ROOT = Path(__file__).parent.parent.parent


def run_evals(
    results: list[dict],
    show,
    evals_path: Path,
) -> list[dict]:
    """Run checks defined in evals_path against beats results.

    Returns a list of check-result dicts with keys: check, status, expected, actual.
    Returns [] if evals_path does not exist.
    """
    if not evals_path.exists():
        return []

    spec = json.loads(evals_path.read_text(encoding="utf-8"))
    checks: list[dict] = []
    ep_index = {r["episode"]: r for r in results}

    # -- resolved_or_soft_endings --
    for ep_num in spec.get("resolved_or_soft_endings", []):
        result = ep_index.get(ep_num)
        if result is None:
            checks.append({
                "check": f"resolved_or_soft_endings E{ep_num:02d}",
                "status": "SKIP",
                "expected": "ends_on_cliffhanger=false",
                "actual": "episode not in results",
            })
            continue
        actual_val = result.get("ending", {}).get("ends_on_cliffhanger")
        passed = actual_val is False
        checks.append({
            "check": f"resolved_or_soft_endings E{ep_num:02d}",
            "status": "PASS" if passed else "FAIL",
            "expected": "ends_on_cliffhanger=false",
            "actual": f"ends_on_cliffhanger={actual_val}",
        })

    # -- min_top_hook_power --
    for entry in spec.get("min_top_hook_power", []):
        ep_num = entry["episode"]
        min_power = entry["min"]
        result = ep_index.get(ep_num)
        if result is None:
            checks.append({
                "check": f"min_top_hook_power E{ep_num:02d}",
                "status": "SKIP",
                "expected": f"best_stop_power>={min_power}",
                "actual": "episode not in results",
            })
            continue
        hooks = result.get("hooks", [])
        best = max((h["stop_power"] for h in hooks), default=0)
        passed = best >= min_power
        checks.append({
            "check": f"min_top_hook_power E{ep_num:02d}",
            "status": "PASS" if passed else "FAIL",
            "expected": f"best_stop_power>={min_power}",
            "actual": f"best_stop_power={best}",
        })

    # -- cliff_types_near_end --
    for entry in spec.get("cliff_types_near_end", []):
        ep_num = entry["episode"]
        allowed_types: list[str] = entry["types"]
        within_last_s: float = entry["within_last_s"]
        result = ep_index.get(ep_num)
        if result is None:
            checks.append({
                "check": f"cliff_types_near_end E{ep_num:02d}",
                "status": "SKIP",
                "expected": f"type in {allowed_types}, within last {within_last_s}s",
                "actual": "episode not in results",
            })
            continue
        cliffs = result.get("cliffhangers", [])
        if not cliffs:
            checks.append({
                "check": f"cliff_types_near_end E{ep_num:02d}",
                "status": "FAIL",
                "expected": f"type in {allowed_types}, within last {within_last_s}s",
                "actual": "no cliffhangers",
            })
            continue
        top = cliffs[0]
        btype = top.get("block_type", "")
        bend = top.get("end", 0.0)
        ep_duration = show.episode_duration(ep_num)
        threshold = ep_duration - within_last_s
        type_ok = btype in allowed_types
        time_ok = bend >= threshold
        passed = type_ok and time_ok
        checks.append({
            "check": f"cliff_types_near_end E{ep_num:02d}",
            "status": "PASS" if passed else "FAIL",
            "expected": (
                f"type in {allowed_types}, "
                f"end>={fmt_time(threshold)} (last {within_last_s}s of "
                f"{fmt_time(ep_duration)})"
            ),
            "actual": f"type={btype}, end={fmt_time(bend)}",
        })

    return checks


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run eval checks on a beats output."
    )
    parser.add_argument("show_dir", type=Path, help="Path to show folder")
    args = parser.parse_args()

    show_dir: Path = args.show_dir.resolve()
    from .parse import make_slug
    slug = make_slug(show_dir.name)

    beats_path = _REPO_ROOT / "outputs" / slug / "beats" / "beats.json"
    if not beats_path.exists():
        sys.exit(f"Error: beats.json not found at {beats_path}")

    data = json.loads(beats_path.read_text(encoding="utf-8"))
    results = data.get("episodes", [])

    from .show import load_show
    show = load_show(show_dir)

    evals_path = _REPO_ROOT / "evals" / f"{slug}.json"
    if not evals_path.exists():
        sys.exit(f"Note: no eval file found at {evals_path} — nothing to check.")

    checks = run_evals(results, show, evals_path)
    for chk in checks:
        print(f"{chk['status']:4s}  {chk['check']}")
        print(f"      expected: {chk['expected']}")
        print(f"      actual:   {chk['actual']}")
        print()


if __name__ == "__main__":
    main()

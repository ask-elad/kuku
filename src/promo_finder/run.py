"""One-command pipeline runner.

CLI: python -m promo_finder.run "<show folder>" [--no-baseline]

Stages (in order):
  1. parse      — build/episodes.json
  2. baseline   — outputs/baseline/promos.json
  3. beats      — outputs/beats/
  4. candidates — outputs/candidates/candidates.json
  5. judge      — outputs/judge/ (pipeline + baseline)
  6. rank       — outputs/final/ + build/review_top10.md
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .show import load_show
from . import llm as _llm


def _run_stage(name: str, cmd: list[str]) -> None:
    print(f"[run] Stage: {name}")
    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        print(f"\nERROR: stage '{name}' failed (exit {result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full promo-finder pipeline.")
    parser.add_argument("show_dir", type=Path, metavar="show_folder")
    parser.add_argument("--no-baseline", action="store_true",
                        help="Skip baseline generation and its judging (saves cost on new shows)")
    args = parser.parse_args()

    show_dir = str(args.show_dir)
    py = sys.executable

    stages: list[tuple[str, list[str]]] = [
        ("parse", [py, "-m", "promo_finder.parse", show_dir]),
    ]

    if not args.no_baseline:
        stages.append(("baseline", [py, "-m", "promo_finder.baseline", show_dir]))

    stages += [
        ("beats", [py, "-m", "promo_finder.beats", show_dir]),
        ("candidates", [py, "-m", "promo_finder.candidates", show_dir]),
    ]

    if args.no_baseline:
        # Judge pipeline only (no baseline available); pass a flag if needed
        # The standard judge run already skips baseline if baseline/promos.json missing
        stages.append(("judge", [py, "-m", "promo_finder.judge", show_dir]))
    else:
        stages.append(("judge", [py, "-m", "promo_finder.judge", show_dir]))
        stages.append(("calibrate", [py, "-m", "promo_finder.judge", show_dir, "--calibrate"]))

    stages.append(("rank", [py, "-m", "promo_finder.rank", show_dir]))

    for name, cmd in stages:
        _run_stage(name, cmd)

    # Summary
    import csv

    show = load_show(args.show_dir)
    slug = show.slug
    final_dir = Path.cwd() / "outputs" / slug / "final"

    total = 0.0
    if _llm._LOG_PATH.exists():
        with _llm._LOG_PATH.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cost_str = row.get("cost_usd", "")
                if cost_str:
                    try:
                        total += float(cost_str)
                    except ValueError:
                        pass

    print(f"\nDone.")
    print(f"  Outputs : {final_dir}/")
    print(f"  Spend   : ${total:.4f}")


if __name__ == "__main__":
    main()

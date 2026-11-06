"""Dumb baseline promo generator: last ~45 s of each episode.

CLI: python -m promo_finder.baseline "<show folder>"
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .promo import resolve
from .validate import EPS, validate

_TARGET_DUR = 45.0
_MIN_DUR = 20.0
_MAX_DUR = 60.0
_HOOK_WINDOW = 3.0
_CLIFF_WINDOW = 5.0


def _is_clean_cut(t: float, blocks: list[dict]) -> bool:
    """Return True if no DIALOGUE block straddles time t (using EPS tolerance)."""
    for bl in blocks:
        if bl["type"] == "DIALOGUE":
            if bl["start"] + EPS < t < bl["end"] - EPS:
                return False
    return True


def _make_episode_promo(ep: dict) -> dict | None:
    blocks: list[dict] = ep["blocks"]
    ep_num: int = ep["episode"]

    if not blocks:
        return None

    # Step 1: end block = block with latest end time; ties → last in file order
    max_end = max(bl["end"] for bl in blocks)
    end_block = None
    for bl in blocks:
        if abs(bl["end"] - max_end) <= EPS:
            end_block = bl  # keeps overwriting → last in file order wins
    assert end_block is not None
    E = end_block["end"]

    # Step 2 + 3: clean start points in range, closest to E − 45
    # Collect one candidate per distinct start time (first block at that time)
    seen_t: dict[int, float] = {}  # rounded_ms → t
    candidates: list[float] = []
    for bl in blocks:
        t = bl["start"]
        key = round(t * 1000)
        if key in seen_t:
            continue
        seen_t[key] = t
        if _MIN_DUR - EPS <= E - t <= _MAX_DUR + EPS and _is_clean_cut(t, blocks):
            candidates.append(t)

    if not candidates:
        return None

    target_t = E - _TARGET_DUR
    # Ties → earlier t, so sort by (distance, t)
    candidates.sort(key=lambda t: (abs(t - target_t), t))
    chosen_t = candidates[0]

    # First block in file order at chosen_t
    start_block = next(bl for bl in blocks if abs(bl["start"] - chosen_t) <= EPS)

    promo_start = start_block["start"]
    promo_end = end_block["end"]

    # Sort blocks by (start_time, file_index) for deterministic candidate ordering
    indexed = sorted(enumerate(blocks), key=lambda ib: (ib[1]["start"], ib[0]))

    # Step 5: hook = first DIALOGUE starting in [promo_start, promo_start + 3 s];
    #          else first ACTION there; else null
    hook_cands = [
        bl for _, bl in indexed
        if promo_start - EPS <= bl["start"] <= promo_start + _HOOK_WINDOW + EPS
        and bl["end"] <= promo_end + EPS
    ]
    hook_block = next((bl for bl in hook_cands if bl["type"] == "DIALOGUE"), None)
    if hook_block is None:
        hook_block = next((bl for bl in hook_cands if bl["type"] == "ACTION"), None)

    # Step 6: cliffhanger = last DIALOGUE/ACTION with end in [promo_end − 5 s, promo_end];
    #          else last DIALOGUE/ACTION in promo
    cliff_window_start = promo_end - _CLIFF_WINDOW
    # "last" = greatest end time, then last in file order for ties
    da_in_promo = [
        (i, bl) for i, bl in enumerate(blocks)
        if bl["type"] in ("DIALOGUE", "ACTION")
        and bl["start"] >= promo_start - EPS
        and bl["end"] <= promo_end + EPS
    ]
    da_by_end = sorted(da_in_promo, key=lambda ib: (ib[1]["end"], ib[0]))

    cliff_block = None
    for _, bl in reversed(da_by_end):
        if bl["end"] >= cliff_window_start - EPS:
            cliff_block = bl
            break
    if cliff_block is None and da_by_end:
        _, cliff_block = da_by_end[-1]

    return {
        "promo_id": f"BASE-E{ep_num:02d}",
        "method": "baseline",
        "segments": [
            {
                "start_block": start_block["id"],
                "end_block": end_block["id"],
            }
        ],
        "hook": (
            {"block_id": hook_block["id"], "text": hook_block["text"]}
            if hook_block else None
        ),
        "cliffhanger": (
            {"block_id": cliff_block["id"], "text": cliff_block["text"]}
            if cliff_block else None
        ),
        "why": f"Baseline: last ~45 s of episode {ep_num}",
        "scores": {},
        "rank": None,
    }


def generate_baseline(show) -> list[dict]:
    """Generate resolved+validated baseline promos for every episode."""
    promos: list[dict] = []
    for ep in show.episodes:
        raw = _make_episode_promo(ep)
        if raw is None:
            continue
        resolved = resolve(raw, show)
        resolved["checks"] = validate(resolved, show)
        promos.append(resolved)
    return promos


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate baseline promos (last ~45 s per episode)."
    )
    parser.add_argument("show_dir", type=Path)
    args = parser.parse_args()

    from .render import render_markdown
    from .show import load_show

    show = load_show(args.show_dir)
    promos = generate_baseline(show)

    out_dir = Path.cwd() / "outputs" / show.slug / "baseline"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "promos.json"
    md_path = out_dir / "promos.md"

    json_path.write_text(
        json.dumps(promos, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(
        render_markdown(promos, f"Baseline Promos — {show.title}"),
        encoding="utf-8",
    )

    valid_count = sum(1 for p in promos if p["checks"]["valid"])
    print(f"Written: {json_path}")
    print(f"Written: {md_path}")
    print(
        f"Promos: {len(promos)}  Valid: {valid_count}  "
        f"Invalid: {len(promos) - valid_count}"
    )


if __name__ == "__main__":
    main()

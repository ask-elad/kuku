"""Promo validator.

CLI: python -m promo_finder.validate <promos.json> --show "<show folder>"
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from .timeutil import fmt_time

EPS = 0.05


def validate(promo: dict, show) -> dict:
    """Run all hard and soft checks on a resolved promo.

    Returns a checks dict: {"hard": {...}, "soft": {...}, "errors": [...], "valid": bool}.
    """
    hard: dict[str, bool] = {}
    soft: dict[str, bool] = {}
    errors: list[str] = []

    segments = promo.get("segments", [])
    hook = promo.get("hook")
    cliff = promo.get("cliffhanger")

    # ------------------------------------------------------------------ #
    # Hard: ids_exist                                                     #
    # ------------------------------------------------------------------ #
    all_ids: list[str] = []
    for seg in segments:
        for key in ("start_block", "end_block"):
            bid = seg.get(key)
            if bid:
                all_ids.append(bid)
    if hook:
        bid = hook.get("block_id")
        if bid:
            all_ids.append(bid)
    if cliff:
        bid = cliff.get("block_id")
        if bid:
            all_ids.append(bid)

    missing = [bid for bid in all_ids if show.block(bid) is None]
    hard["ids_exist"] = len(missing) == 0
    if missing:
        errors.append(f"Unknown block IDs: {', '.join(sorted(missing))}")

    # ------------------------------------------------------------------ #
    # Hard: segment_same_episode                                          #
    # ------------------------------------------------------------------ #
    same_ep_ok = True
    for seg in segments:
        sb = show.block(seg.get("start_block", ""))
        eb = show.block(seg.get("end_block", ""))
        if sb is not None and eb is not None and sb["episode"] != eb["episode"]:
            same_ep_ok = False
            errors.append(
                f"Segment {seg['start_block']}..{seg['end_block']}: "
                f"episodes {sb['episode']} vs {eb['episode']}"
            )
    hard["segment_same_episode"] = same_ep_ok

    # ------------------------------------------------------------------ #
    # Hard: segment_order  (start < end, duration >= 1.0)                #
    # ------------------------------------------------------------------ #
    order_ok = True
    for seg in segments:
        start = seg.get("start")
        end = seg.get("end")
        if start is None or end is None:
            order_ok = False
            continue
        if end <= start + EPS or (end - start) < 1.0 - EPS:
            order_ok = False
            errors.append(
                f"Segment {seg.get('start_block')}..{seg.get('end_block')}: "
                f"start={fmt_time(start)} end={fmt_time(end)} "
                f"dur={end - start:.2f} s"
            )
    hard["segment_order"] = order_ok

    # ------------------------------------------------------------------ #
    # Hard: no_overlap                                                    #
    # ------------------------------------------------------------------ #
    overlap_ok = True
    ep_segs: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for seg in segments:
        ep_num = seg.get("episode")
        start = seg.get("start")
        end = seg.get("end")
        if ep_num is not None and start is not None and end is not None:
            ep_segs[ep_num].append((start, end))

    for ep_num, segs in ep_segs.items():
        sorted_segs = sorted(segs)
        for i in range(len(sorted_segs) - 1):
            a_end = sorted_segs[i][1]
            b_start = sorted_segs[i + 1][0]
            if a_end > b_start + EPS:
                overlap_ok = False
                errors.append(
                    f"Segments in E{ep_num:02d} overlap: "
                    f"{fmt_time(sorted_segs[i][0])}-{fmt_time(a_end)} and "
                    f"{fmt_time(b_start)}-{fmt_time(sorted_segs[i + 1][1])}"
                )
    hard["no_overlap"] = overlap_ok

    # ------------------------------------------------------------------ #
    # Hard: duration_20_60                                                #
    # ------------------------------------------------------------------ #
    total_dur = promo.get("duration", 0.0)
    dur_ok = 20.0 - EPS <= total_dur <= 60.0 + EPS
    hard["duration_20_60"] = dur_ok
    if not dur_ok:
        errors.append(f"Promo duration {total_dur:.2f} s not in [20, 60]")

    # ------------------------------------------------------------------ #
    # Hard: no_mid_line_cut                                               #
    # ------------------------------------------------------------------ #
    no_cut_ok = True
    for seg in segments:
        ep_num = seg.get("episode")
        start = seg.get("start")
        end = seg.get("end")
        if ep_num is None or start is None or end is None:
            continue
        ep_dict = show._episode_index.get(ep_num)
        if ep_dict is None:
            continue
        for t in (start, end):
            for bl in ep_dict["blocks"]:
                if bl["type"] == "DIALOGUE":
                    if bl["start"] + EPS < t < bl["end"] - EPS:
                        no_cut_ok = False
                        errors.append(
                            f"Cut at {fmt_time(t)} falls mid-line of "
                            f"block {bl['id']} "
                            f"({fmt_time(bl['start'])}-{fmt_time(bl['end'])})"
                        )
    hard["no_mid_line_cut"] = no_cut_ok

    # ------------------------------------------------------------------ #
    # Hard: hook_inside / cliff_inside                                    #
    # ------------------------------------------------------------------ #
    def _inside_segments(block_id: str | None) -> bool:
        if block_id is None:
            return True
        bl = show.block(block_id)
        if bl is None:
            return False
        for seg in segments:
            if seg.get("episode") != bl["episode"]:
                continue
            seg_start = seg.get("start")
            seg_end = seg.get("end")
            if seg_start is None or seg_end is None:
                continue
            if seg_start - EPS <= bl["start"] and bl["end"] <= seg_end + EPS:
                return True
        return False

    hook_id = hook.get("block_id") if hook else None
    cliff_id = cliff.get("block_id") if cliff else None

    hook_inside_ok = _inside_segments(hook_id)
    cliff_inside_ok = _inside_segments(cliff_id)
    hard["hook_inside"] = hook_inside_ok
    hard["cliff_inside"] = cliff_inside_ok
    if not hook_inside_ok and hook_id:
        errors.append(f"Hook block {hook_id} not inside any segment")
    if not cliff_inside_ok and cliff_id:
        errors.append(f"Cliffhanger block {cliff_id} not inside any segment")

    # ------------------------------------------------------------------ #
    # Soft checks                                                         #
    # ------------------------------------------------------------------ #
    soft["has_hook"] = hook is not None
    soft["has_cliffhanger"] = cliff is not None

    if hook and hook.get("at") is not None:
        soft["hook_in_first_3s"] = hook["at"] <= 3.0 + EPS
    else:
        soft["hook_in_first_3s"] = False

    if cliff and cliff.get("block_id"):
        cl_bl = show.block(cliff["block_id"])
        if cl_bl is not None and cliff.get("at") is not None:
            cliff_end_in_promo = cliff["at"] + (cl_bl["end"] - cl_bl["start"])
            soft["cliff_in_last_5s"] = cliff_end_in_promo >= total_dur - 5.0 - EPS
        else:
            soft["cliff_in_last_5s"] = False
    else:
        soft["cliff_in_last_5s"] = False

    return {
        "hard": hard,
        "soft": soft,
        "errors": errors,
        "valid": all(hard.values()),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _report(promos: list[dict]) -> str:
    total = len(promos)
    valid_count = sum(1 for p in promos if p.get("checks", {}).get("valid", False))
    lines = [
        f"Promos: {total}  Valid: {valid_count}  Invalid: {total - valid_count}",
    ]

    hard_names = [
        "ids_exist", "segment_same_episode", "segment_order", "no_overlap",
        "duration_20_60", "no_mid_line_cut", "hook_inside", "cliff_inside",
    ]
    soft_names = [
        "has_hook", "has_cliffhanger", "hook_in_first_3s", "cliff_in_last_5s",
    ]

    lines.append("\nHard check failures:")
    any_fail = False
    for name in hard_names:
        fails = sum(
            1 for p in promos
            if not p.get("checks", {}).get("hard", {}).get(name, True)
        )
        if fails:
            any_fail = True
            lines.append(f"  {name}: {fails} failure(s)")
    if not any_fail:
        lines.append("  none")

    lines.append("\nSoft check pass rates:")
    for name in soft_names:
        passes = sum(
            1 for p in promos
            if p.get("checks", {}).get("soft", {}).get(name, False)
        )
        pct = 100 * passes // total if total else 0
        lines.append(f"  {name}: {passes}/{total} ({pct}%)")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a promos.json file and print a report."
    )
    parser.add_argument("promos_json", type=Path)
    parser.add_argument("--show", required=True, type=Path, dest="show_dir")
    args = parser.parse_args()

    from .show import load_show
    from .promo import resolve

    show = load_show(args.show_dir)
    promos_raw = json.loads(args.promos_json.read_text(encoding="utf-8"))

    promos: list[dict] = []
    for p in promos_raw:
        resolved = resolve(p, show)
        resolved["checks"] = validate(resolved, show)
        promos.append(resolved)

    print(_report(promos))


if __name__ == "__main__":
    main()

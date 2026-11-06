"""Promo data format and resolve() function."""
from __future__ import annotations

import copy

from .timeutil import fmt_time


def resolve(promo: dict, show) -> dict:
    """Return a new promo dict with all derived fields filled in.

    Adds per-segment times, promo duration, and hook/cliffhanger `at` offsets.
    Never mutates the input dict.
    """
    p = copy.deepcopy(promo)

    resolved_segments: list[dict] = []
    cum_duration = 0.0
    # (seg_start, seg_end, seg_episode, cum_before) for each resolved segment
    seg_times: list[tuple[float, float, int, float] | None] = []

    for seg in p.get("segments", []):
        sb = show.block(seg.get("start_block", ""))
        eb = show.block(seg.get("end_block", ""))
        if sb is None or eb is None:
            resolved_segments.append(dict(seg))
            seg_times.append(None)
            continue

        episode = sb["episode"]
        start = sb["start"]
        end = eb["end"]
        duration = end - start

        rseg = dict(seg)
        rseg["episode"] = episode
        rseg["start"] = start
        rseg["end"] = end
        rseg["start_tc"] = fmt_time(start)
        rseg["end_tc"] = fmt_time(end)
        rseg["duration"] = duration

        seg_times.append((start, end, episode, cum_duration))
        cum_duration += max(duration, 0.0)
        resolved_segments.append(rseg)

    p["segments"] = resolved_segments
    p["duration"] = cum_duration

    for field in ("hook", "cliffhanger"):
        hc = p.get(field)
        if not hc:
            continue
        bid = hc.get("block_id")
        if not bid:
            continue
        bl = show.block(bid)
        if bl is None:
            continue
        for i, st in enumerate(seg_times):
            if st is None:
                continue
            seg_start, seg_end, seg_ep, cum_before = st
            if bl["episode"] == seg_ep and seg_start <= bl["start"] <= seg_end:
                hc["at"] = cum_before + (bl["start"] - seg_start)
                break

    return p

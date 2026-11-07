"""Format episode blocks into the script text the LLM receives."""
from __future__ import annotations

import re

from .timeutil import fmt_time

_CLIFFHANGER_RE = re.compile(r"cliff-?hangers?", re.IGNORECASE)

_EPS = 0.05


def format_blocks(blocks: list[dict], scenes: dict[str, dict] | None = None) -> str:
    """Return one line per block; insert scene headers on scene changes.

    scenes: optional dict of scene_id -> scene dict (with 'heading' key).
    """
    lines: list[str] = []
    current_scene: str | None = None

    for bl in blocks:
        sid = bl.get("scene_id", "")
        if sid != current_scene:
            current_scene = sid
            if scenes and sid in scenes:
                heading = scenes[sid].get("heading", "")
                lines.append(f"== SCENE {sid}: {heading} ==")
            elif sid:
                lines.append(f"== SCENE {sid} ==")

        btype = bl["type"]
        bid = bl["id"]
        time_range = f"{fmt_time(bl['start'])}–{fmt_time(bl['end'])}"

        if btype == "DIALOGUE":
            text = f"{bl['label_raw']}: {bl['text']}"
        else:
            text = bl["text"]

        lines.append(f"{bid} | {time_range} | {btype} | {text}")

    return "\n".join(lines)


def format_clip(promo: dict, show) -> str:
    """Format a resolved promo as clip text for the LLM judge.

    Times are rebased so the clip starts at 00:00. Segments are separated by
    == CUT ==. No block IDs, episode numbers, or scene IDs appear; only the
    scene heading text (e.g. INT. HALL – DAY) is shown on scene changes.

    Line format: 00:03.20–00:05.10 | DIALOGUE | GERALD (Cold): text
    """
    segments = promo.get("segments", [])
    parts: list[str] = []
    cum_offset = 0.0

    for seg in segments:
        ep_num = seg.get("episode")
        seg_start = seg.get("start")
        seg_end = seg.get("end")

        if ep_num is None or seg_start is None or seg_end is None:
            cum_offset += max(0.0, (seg_end or 0.0) - (seg_start or 0.0))
            continue

        ep_dict = show._episode_index.get(ep_num)
        if ep_dict is None:
            cum_offset += max(0.0, seg_end - seg_start)
            continue

        scenes: dict[str, str] = {
            s["id"]: s.get("heading", "")
            for s in ep_dict.get("scenes", [])
        }

        blocks = [
            bl for bl in ep_dict["blocks"]
            if bl["start"] >= seg_start - _EPS and bl["start"] < seg_end
        ]

        segment_lines: list[str] = []
        current_scene: str | None = None

        for bl in blocks:
            sid = bl.get("scene_id", "")
            if sid != current_scene:
                current_scene = sid
                heading = scenes.get(sid, "")
                if heading:
                    segment_lines.append(heading)

            bl_start_promo = cum_offset + (bl["start"] - seg_start)
            bl_end_promo = cum_offset + (bl["end"] - seg_start)
            time_range = f"{fmt_time(bl_start_promo)}–{fmt_time(bl_end_promo)}"

            btype = bl["type"]
            if btype == "DIALOGUE":
                line = f"{time_range} | {btype} | {bl['label_raw']}: {bl['text']}"
            else:
                line = f"{time_range} | {btype} | {bl['text']}"

            segment_lines.append(line)

        parts.append("\n".join(segment_lines))
        cum_offset += seg_end - seg_start

    result = "\n== CUT ==\n".join(parts)
    return _CLIFFHANGER_RE.sub("moment", result)

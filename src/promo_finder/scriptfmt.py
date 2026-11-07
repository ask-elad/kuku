"""Format episode blocks into the script text the LLM receives."""
from __future__ import annotations

from .timeutil import fmt_time


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

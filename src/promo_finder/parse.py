"""Parse screenplay .txt files into structured JSON.

CLI: python -m promo_finder.parse "<show folder>" [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from statistics import mean

from .timeutil import fmt_time, parse_time

# Stage-direction tokens that appear in block labels but are not delivery tags.
_STAGE_DIR_RE = re.compile(r"^(?:O\.S\.|V\.O\.)$", re.IGNORECASE)
_STAGE_DIR_SLASH_RE = re.compile(r"^(?:O\.S\.|V\.O\.)\s*/\s*", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Slug helper
# ---------------------------------------------------------------------------

def make_slug(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


# ---------------------------------------------------------------------------
# Label parsing
# ---------------------------------------------------------------------------

def parse_label(label_raw: str) -> tuple[str, str | None, list[str]]:
    """Return (block_type, speaker|None, delivery_list)."""
    label = label_raw.strip()
    upper = label.upper()

    if upper == "CAMERA":
        return "CAMERA", None, []
    if upper == "ACTION":
        return "ACTION", None, []
    if upper in ("SOUND FX", "SOUND_FX"):
        return "SOUND_FX", None, []

    paren_pos = label.find("(")
    if paren_pos >= 0:
        speaker = label[:paren_pos].strip()
    else:
        speaker = label.strip()

    if not speaker:
        return "OTHER", None, []

    paren_groups = re.findall(r"\(([^)]*)\)", label)
    delivery: list[str] = []
    for group in paren_groups:
        g = group.strip()
        if _STAGE_DIR_RE.match(g):
            continue
        m = _STAGE_DIR_SLASH_RE.match(g)
        if m:
            rest = g[m.end():].strip()
            delivery = [d.strip() for d in rest.split(",") if d.strip()]
        else:
            delivery = [d.strip() for d in g.split(",") if d.strip()]

    return "DIALOGUE", speaker, delivery


# ---------------------------------------------------------------------------
# Episode parser
# ---------------------------------------------------------------------------

def _extract_episode_number(text: str) -> int | None:
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


def parse_episode(filepath: Path) -> tuple[dict, list[str]]:
    """Parse one episode .txt file.

    Returns (episode_dict, warnings_list).  Every non-empty line of the file
    is accounted for; unrecognised lines appear in warnings_list.
    """
    raw = filepath.read_text(encoding="utf-8")
    lines = raw.splitlines()
    n = len(lines)
    consumed = bytearray(n)
    warns: list[str] = []
    fname = filepath.name

    # Pre-consume all blank lines.
    for i, line in enumerate(lines):
        if not line.strip():
            consumed[i] = 1

    # ------------------------------------------------------------------ #
    # Phase 1 – episode header                                            #
    # ------------------------------------------------------------------ #
    ep_number: int | None = None
    logline = ""
    continuity_notes = ""
    script_start_idx: int | None = None

    i = 0
    while i < n:
        s = lines[i].strip()

        if re.match(r"^---\s*SCRIPT START\s*---", s, re.I):
            consumed[i] = 1
            script_start_idx = i
            i += 1
            break

        m = re.match(r"^EPISODE NUMBER:\s*(.*)", s, re.I)
        if m:
            ep_number = _extract_episode_number(m.group(1).strip())
            consumed[i] = 1
            i += 1
            continue

        m = re.match(r"^EPISODE LOGLINE:\s*(.*)", s, re.I)
        if m:
            logline = m.group(1).strip()
            consumed[i] = 1
            i += 1
            while i < n:
                s2 = lines[i].strip()
                if not s2 or re.match(r"^(?:EPISODE|CONTINUITY|---)", s2, re.I):
                    break
                logline += " " + s2
                consumed[i] = 1
                i += 1
            continue

        m = re.match(r"^CONTINUITY NOTES:\s*(.*)", s, re.I)
        if m:
            continuity_notes = m.group(1).strip()
            consumed[i] = 1
            i += 1
            while i < n:
                s2 = lines[i].strip()
                if not s2 or re.match(r"^(?:EPISODE|---)", s2, re.I):
                    break
                continuity_notes += " " + s2
                consumed[i] = 1
                i += 1
            continue

        i += 1

    # ------------------------------------------------------------------ #
    # Locate SCRIPT END                                                   #
    # ------------------------------------------------------------------ #
    script_end_idx: int | None = None
    start = (script_start_idx + 1) if script_start_idx is not None else 0
    for j in range(start, n):
        if re.match(r"^---\s*SCRIPT END\s*---", lines[j].strip(), re.I):
            consumed[j] = 1
            script_end_idx = j
            break

    if ep_number is None:
        warns.append(f"{fname}: EPISODE NUMBER not found")

    # Cross-check episode number against filename (episode-NNN-…).
    fn_m = re.match(r"^episode-(\d+)-", fname, re.I)
    fn_ep = int(fn_m.group(1)) if fn_m else None
    if fn_ep is not None and ep_number is not None and fn_ep != ep_number:
        warns.append(
            f"{fname}: filename episode {fn_ep} != header episode {ep_number}"
        )
    effective_ep = ep_number or fn_ep or 0

    # ------------------------------------------------------------------ #
    # Phase 2 – script body                                               #
    # ------------------------------------------------------------------ #
    scenes: list[dict] = []
    blocks: list[dict] = []
    scene_count = 0
    block_count = 0
    current_scene_id = ""
    current_scene: dict | None = None

    j = (script_start_idx + 1) if script_start_idx is not None else 0
    body_end = script_end_idx if script_end_idx is not None else n

    while j < body_end:
        s = lines[j].strip()

        # ---- Scene header: "SCENE 01" ----------------------------------
        if re.match(r"^SCENE\s+\d+\s*$", s, re.I):
            scene_num = int(re.search(r"\d+", s).group())
            scene_count += 1
            ep_tag = f"E{effective_ep:02d}"
            scene_id = f"{ep_tag}-S{scene_count:02d}"
            consumed[j] = 1
            j += 1

            heading = ""
            scene_start = 0.0
            scene_end_t = 0.0

            while j < body_end:
                s2 = lines[j].strip()
                if not s2:
                    consumed[j] = 1
                    j += 1
                    continue

                m2 = re.match(r"^scene heading:\s*(.*)", s2, re.I)
                if m2:
                    heading = m2.group(1).strip()
                    consumed[j] = 1
                    j += 1
                    continue

                m2 = re.match(r"^scene start:\s*(.*)", s2, re.I)
                if m2:
                    try:
                        scene_start = parse_time(m2.group(1).strip())
                    except Exception:
                        warns.append(f"{fname} line {j+1}: bad scene start time")
                    consumed[j] = 1
                    j += 1
                    continue

                m2 = re.match(r"^scene end:\s*(.*)", s2, re.I)
                if m2:
                    try:
                        scene_end_t = parse_time(m2.group(1).strip())
                    except Exception:
                        warns.append(f"{fname} line {j+1}: bad scene end time")
                    consumed[j] = 1
                    j += 1
                    continue

                if re.match(r"^actions and dialogue:", s2, re.I):
                    consumed[j] = 1
                    j += 1
                    break

                # Hit a block label or unknown line – stop scene meta.
                break

            scenes.append(
                {
                    "id": scene_id,
                    "number": scene_num,
                    "heading": heading,
                    "start": scene_start,
                    "end": scene_end_t,
                }
            )
            current_scene_id = scene_id
            current_scene = scenes[-1]
            continue

        # ---- Block label: **LABEL:** -----------------------------------
        m = re.match(r"^\*\*(.+?):\*\*$", s)
        if m:
            label_raw = m.group(1).strip()
            consumed[j] = 1
            j += 1

            # Timestamp line
            ts_start = 0.0
            ts_end = 0.0
            if j < body_end:
                s2 = lines[j].strip()
                ts_m = re.match(
                    r"^[Ss]tart:\s*\(([^)]+)\)\s*\|\s*[Ee]nd:\s*\(([^)]+)\)",
                    s2,
                )
                if ts_m:
                    try:
                        ts_start = parse_time(ts_m.group(1))
                        ts_end = parse_time(ts_m.group(2))
                    except Exception:
                        warns.append(
                            f"{fname} line {j+1}: bad block timestamp"
                        )
                    consumed[j] = 1
                    j += 1

            # Text lines
            text_parts: list[str] = []
            while j < body_end:
                s2 = lines[j].strip()
                if not s2:
                    consumed[j] = 1
                    j += 1
                    break
                # Next block label or scene header – stop.
                if re.match(r"^\*\*.+:\*\*$", s2) or re.match(
                    r"^SCENE\s+\d+\s*$", s2, re.I
                ):
                    break
                text_parts.append(s2)
                consumed[j] = 1
                j += 1

            block_count += 1
            block_id = f"E{effective_ep:02d}-B{block_count:03d}"

            btype, speaker, delivery = parse_label(label_raw)

            if btype == "OTHER":
                warns.append(
                    f"{fname}: Unknown label {label_raw!r} at block {block_id}"
                )

            text = " ".join(text_parts)
            if btype == "DIALOGUE" and text.startswith('"') and text.endswith('"'):
                text = text[1:-1]

            if ts_end < ts_start:
                warns.append(
                    f"{fname} block {block_id}: "
                    f"end ({fmt_time(ts_end)}) < start ({fmt_time(ts_start)})"
                )

            if current_scene is not None:
                sc = current_scene
                if ts_start < sc["start"] - 0.01 or ts_end > sc["end"] + 0.01:
                    warns.append(
                        f"{fname} block {block_id}: "
                        f"time {fmt_time(ts_start)}-{fmt_time(ts_end)} "
                        f"outside scene {current_scene_id} "
                        f"{fmt_time(sc['start'])}-{fmt_time(sc['end'])}"
                    )

            blocks.append(
                {
                    "id": block_id,
                    "episode": effective_ep,
                    "scene_id": current_scene_id,
                    "type": btype,
                    "label_raw": label_raw,
                    "speaker": speaker,
                    "delivery": delivery,
                    "start": ts_start,
                    "end": ts_end,
                    "text": text,
                }
            )
            continue

        j += 1

    # ------------------------------------------------------------------ #
    # Duration and unconsumed-line report                                 #
    # ------------------------------------------------------------------ #
    duration = 0.0
    for sc in scenes:
        duration = max(duration, sc["end"])
    for bl in blocks:
        duration = max(duration, bl["end"])

    for idx in range(n):
        if not consumed[idx] and lines[idx].strip():
            warns.append(
                f"{fname} line {idx+1}: unconsumed: {lines[idx][:60]!r}"
            )

    return (
        {
            "episode": effective_ep,
            "source_file": fname,
            "logline": logline,
            "continuity_notes": continuity_notes,
            "duration": duration,
            "scenes": scenes,
            "blocks": blocks,
        },
        warns,
    )


# ---------------------------------------------------------------------------
# Show-level parser
# ---------------------------------------------------------------------------

def parse_show(show_dir: Path) -> tuple[dict, list[str]]:
    """Parse all episode files under show_dir. Returns (output_dict, warnings)."""
    files = sorted(
        show_dir.glob("episode-*.txt"),
        key=lambda p: int(re.search(r"^episode-(\d+)-", p.name, re.I).group(1)),
    )
    if not files:
        return {}, [f"No episode-*.txt files found in {show_dir}"]

    title = show_dir.name
    slug = make_slug(title)
    all_warns: list[str] = []
    episodes: list[dict] = []

    for fp in files:
        ep_dict, ep_warns = parse_episode(fp)
        episodes.append(ep_dict)
        all_warns.extend(ep_warns)

    return (
        {
            "show": {"title": title, "slug": slug, "n_episodes": len(episodes)},
            "episodes": episodes,
        },
        all_warns,
    )


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def _print_summary(output: dict, warns: list[str]) -> None:
    episodes = output.get("episodes", [])
    total_scenes = sum(len(ep["scenes"]) for ep in episodes)
    total_blocks = sum(len(ep["blocks"]) for ep in episodes)

    type_counts: dict[str, int] = {}
    for ep in episodes:
        for bl in ep["blocks"]:
            type_counts[bl["type"]] = type_counts.get(bl["type"], 0) + 1

    durations = [ep["duration"] for ep in episodes]
    total_dur = sum(durations)
    min_dur = min(durations) if durations else 0.0
    max_dur = max(durations) if durations else 0.0
    mean_dur = mean(durations) if durations else 0.0

    print(
        f"Parsed: {len(episodes)} episodes, "
        f"{total_scenes} scenes, {total_blocks} blocks"
    )

    type_str = "  ".join(
        f"{t}={type_counts.get(t, 0)}"
        for t in ("CAMERA", "ACTION", "DIALOGUE", "SOUND_FX", "OTHER")
    )
    print(f"Block types: {type_str}")

    print(
        f"Duration: min={fmt_time(min_dur)}  max={fmt_time(max_dur)}"
        f"  mean={fmt_time(mean_dur)}  total={fmt_time(total_dur)}"
    )

    if warns:
        print(f"\nWarnings ({len(warns)}):")
        for w in warns:
            print(f"  {w}")
    else:
        print("Warnings: 0")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse screenplay .txt files into structured JSON."
    )
    parser.add_argument("show_dir", type=Path, help="Path to show folder")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path (default: build/<slug>/episodes.json)",
    )
    args = parser.parse_args()

    show_dir: Path = args.show_dir.resolve()
    if not show_dir.is_dir():
        sys.exit(f"Error: {show_dir} is not a directory")

    output, warns = parse_show(show_dir)
    if not output:
        sys.exit(warns[0] if warns else "Nothing parsed")

    slug = output["show"]["slug"]
    out_path: Path = args.out or (Path.cwd() / "build" / slug / "episodes.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"Written: {out_path}\n")

    _print_summary(output, warns)


if __name__ == "__main__":
    main()

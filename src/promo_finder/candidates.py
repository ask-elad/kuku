"""Build candidate promo clips from beats.

CLI: python -m promo_finder.candidates "<show folder>"
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from .promo import resolve
from .validate import validate, EPS
from .show import load_show


# ---------------------------------------------------------------------------
# Beat helpers
# ---------------------------------------------------------------------------

def _merge_cliffhangers(cliffs: list[dict]) -> tuple[list[dict], int]:
    """Merge cliffhangers within 1.0 s of each other.

    Sort by end time. If two adjacent cliffs are within 1.0 s, they go in the
    same group; keep the one with highest tension (tie → later end).
    Returns (merged_list, merge_count).
    """
    if not cliffs:
        return [], 0
    sorted_cliffs = sorted(cliffs, key=lambda c: c["end"])
    groups: list[list[dict]] = [[sorted_cliffs[0]]]
    for c in sorted_cliffs[1:]:
        if c["end"] - groups[-1][-1]["end"] <= 1.0:
            groups[-1].append(c)
        else:
            groups.append([c])

    result: list[dict] = []
    merge_count = 0
    for group in groups:
        if len(group) == 1:
            result.append(group[0])
        else:
            merge_count += len(group) - 1
            best = max(group, key=lambda c: (c["tension"], c["end"]))
            result.append(best)
    return result, merge_count


def _first_block_at(ep: dict, t: float) -> dict | None:
    """First block in file order whose start == t (within EPS)."""
    for bl in ep["blocks"]:
        if abs(bl["start"] - t) <= EPS:
            return bl
    return None


def _last_dialogue_or_action(ep: dict) -> dict | None:
    """Last DIALOGUE or ACTION block by end time; ties → last in file order."""
    best: dict | None = None
    for bl in ep["blocks"]:
        if bl["type"] not in ("DIALOGUE", "ACTION"):
            continue
        if best is None or bl["end"] > best["end"] or abs(bl["end"] - best["end"]) <= EPS:
            best = bl
    return best


def _first_block(ep: dict) -> dict | None:
    """Block with the earliest start; ties → first in file order."""
    if not ep["blocks"]:
        return None
    best = ep["blocks"][0]
    for bl in ep["blocks"][1:]:
        if bl["start"] < best["start"] - EPS:
            best = bl
    return best


# ---------------------------------------------------------------------------
# Promo dict builder
# ---------------------------------------------------------------------------

def _make_raw(seg1_start_id: str, seg1_end_id: str,
              seg2_start_id: str | None, seg2_end_id: str | None,
              hook: dict, cliff: dict) -> dict:
    segments: list[dict] = [{"start_block": seg1_start_id, "end_block": seg1_end_id}]
    if seg2_start_id and seg2_end_id:
        segments.append({"start_block": seg2_start_id, "end_block": seg2_end_id})
    return {
        "segments": segments,
        "hook": {"block_id": hook["block_id"]},
        "cliffhanger": {"block_id": cliff["block_id"]},
        "beat_notes": {
            "hook_why": hook.get("why", ""),
            "hook_type": hook.get("type", ""),
            "stop_power": hook.get("stop_power", 0),
            "open_question": cliff.get("open_question", ""),
            "tension": cliff.get("tension", 0),
        },
        "why": "",
        "method": "pipeline",
    }


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_candidates(show, beats_data: dict) -> dict:
    """Build, filter, and ID all candidate promos.

    Returns {"candidates": [...], "stats": {...}}.
    """
    eps_by_num: dict[int, dict] = {ep["episode"]: ep for ep in show.episodes}

    # ------------------------------------------------------------------ A1
    skipped_no_clean = 0
    all_hooks: list[tuple[int, dict]] = []
    cliffs_by_ep: dict[int, list[dict]] = {}
    total_merges = 0

    for ep_data in beats_data["episodes"]:
        ep_num = ep_data["episode"]
        for h in ep_data.get("hooks", []):
            if h.get("clean_start") is None:
                skipped_no_clean += 1
            else:
                all_hooks.append((ep_num, h))

        raw_cliffs = ep_data.get("cliffhangers", [])
        merged, n_merges = _merge_cliffhangers(raw_cliffs)
        cliffs_by_ep[ep_num] = merged
        total_merges += n_merges

    # ------------------------------------------------------------------ A2
    raw_candidates: list[dict] = []

    for ep_num, h in all_hooks:
        ep = eps_by_num.get(ep_num)
        if ep is None:
            continue
        start_bl = _first_block_at(ep, h["clean_start"])
        if start_bl is None:
            continue

        # Singles
        for c in cliffs_by_ep.get(ep_num, []):
            if c["start"] >= h["start"] and c["block_id"] != h["block_id"]:
                raw_candidates.append(
                    _make_raw(start_bl["id"], c["block_id"], None, None, h, c)
                )

        # Bridges
        next_ep = eps_by_num.get(ep_num + 1)
        if next_ep is not None:
            last_da = _last_dialogue_or_action(ep)
            first_next = _first_block(next_ep)
            if last_da and first_next:
                for c in cliffs_by_ep.get(ep_num + 1, []):
                    raw_candidates.append(
                        _make_raw(start_bl["id"], last_da["id"],
                                  first_next["id"], c["block_id"], h, c)
                    )

    # ------------------------------------------------------------------ A3.1
    rejection_counts: dict[str, int] = defaultdict(int)
    resolved_valid: list[dict] = []

    for raw in raw_candidates:
        resolved = resolve(raw, show)
        checks = validate(resolved, show)
        resolved["checks"] = checks
        if checks["valid"]:
            resolved_valid.append(resolved)
        else:
            for name, passed in checks["hard"].items():
                if not passed:
                    rejection_counts[name] += 1

    # ------------------------------------------------------------------ A3.2 per-hook selection
    def _select_key(r: dict) -> tuple:
        tension = r["beat_notes"]["tension"]
        dur = r.get("duration", 0.0)
        cliff_at = (r["cliffhanger"].get("at", float("inf"))
                    if r.get("cliffhanger") else float("inf"))
        return (-tension, abs(dur - 37.5), cliff_at)

    singles_by_hook: dict[str, list[dict]] = defaultdict(list)
    bridges_by_hook: dict[str, list[dict]] = defaultdict(list)
    for r in resolved_valid:
        hid = r["hook"]["block_id"]
        (singles_by_hook if len(r["segments"]) == 1 else bridges_by_hook)[hid].append(r)

    after_selection: list[dict] = []
    for hid in sorted(set(list(singles_by_hook) + list(bridges_by_hook))):
        if singles_by_hook[hid]:
            after_selection.append(sorted(singles_by_hook[hid], key=_select_key)[0])
        if bridges_by_hook[hid]:
            after_selection.append(sorted(bridges_by_hook[hid], key=_select_key)[0])

    # Sort for determinism before dedup
    after_selection.sort(key=lambda c: (
        c["segments"][0].get("episode", 0),
        c["segments"][0].get("start", 0.0),
    ))

    # ------------------------------------------------------------------ A3.3 exact-duplicate removal
    # Remove candidates with identical segment lists only (D21: overlap dedup moves to Task 06).
    def _seg_key(c: dict) -> tuple:
        return tuple(
            (s.get("start_block", ""), s.get("end_block", ""))
            for s in c.get("segments", [])
        )

    seen_keys: set[tuple] = set()
    final: list[dict] = []
    removed_dedup = 0
    for c in after_selection:
        k = _seg_key(c)
        if k in seen_keys:
            removed_dedup += 1
        else:
            seen_keys.add(k)
            final.append(c)

    # ------------------------------------------------------------------ A4 assign IDs
    by_ep: dict[int, list[dict]] = defaultdict(list)
    for c in final:
        ep_n = c["segments"][0].get("episode", 0)
        by_ep[ep_n].append(c)

    for ep_n in sorted(by_ep):
        ep_cands = sorted(by_ep[ep_n], key=lambda c: c["segments"][0].get("start", 0.0))
        for idx, c in enumerate(ep_cands, 1):
            c["promo_id"] = f"C-E{ep_n:02d}-{idx:02d}"

    return {
        "candidates": final,
        "stats": {
            "skipped_no_clean_start": skipped_no_clean,
            "total_merges": total_merges,
            "rejected": dict(rejection_counts),
            "removed_dedup": removed_dedup,
        },
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _build_report(result: dict) -> str:
    candidates = result["candidates"]
    stats = result["stats"]
    total = len(candidates)
    singles = sum(1 for c in candidates if len(c["segments"]) == 1)
    bridges = total - singles

    lines: list[str] = []
    lines.append("# Candidates Report\n")
    lines.append(f"**Total candidates:** {total}")
    lines.append(f"**Singles:** {singles}  **Bridges:** {bridges}\n")

    # Per-episode counts
    by_ep: dict[int, int] = defaultdict(int)
    for c in candidates:
        ep_n = c["segments"][0].get("episode", 0)
        by_ep[ep_n] += 1
    lines.append("## Per Starting Episode\n")
    lines.append("| Episode | Count |")
    lines.append("|---------|-------|")
    for ep_n in sorted(by_ep):
        lines.append(f"| E{ep_n:02d}     | {by_ep[ep_n]}     |")
    lines.append("")

    # Duration histogram (10 s bins)
    bins = [0] * 5  # [20-30), [30-40), [40-50), [50-60], others
    bin_labels = ["20–30 s", "30–40 s", "40–50 s", "50–60 s", "other"]
    for c in candidates:
        dur = c.get("duration", 0.0)
        if 20 <= dur < 30:
            bins[0] += 1
        elif 30 <= dur < 40:
            bins[1] += 1
        elif 40 <= dur < 50:
            bins[2] += 1
        elif 50 <= dur <= 60:
            bins[3] += 1
        else:
            bins[4] += 1

    lines.append("## Duration Histogram\n")
    lines.append("| Bin     | Count |")
    lines.append("|---------|-------|")
    for label, count in zip(bin_labels, bins):
        lines.append(f"| {label:<7} | {count}     |")
    lines.append("")

    # Drops/skips/merges
    lines.append("## Drops, Skips, Merges\n")
    lines.append(f"- Hooks skipped (no clean_start): **{stats['skipped_no_clean_start']}**")
    lines.append(f"- Cliffhanger merges: **{stats['total_merges']}**")
    lines.append(f"- Near-duplicate removals: **{stats['removed_dedup']}**")
    lines.append("")
    lines.append("### Rejections by Hard Check\n")
    rejected = stats["rejected"]
    if rejected:
        for check_name, count in sorted(rejected.items()):
            lines.append(f"- {check_name}: {count}")
    else:
        lines.append("- None")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build candidate promo clips from beats."
    )
    parser.add_argument("show_dir", type=Path, metavar="show_folder")
    args = parser.parse_args()

    show = load_show(args.show_dir)
    slug = show.slug

    beats_path = Path.cwd() / "outputs" / slug / "beats" / "beats.json"
    if not beats_path.exists():
        print(f"ERROR: beats.json not found at {beats_path}", file=sys.stderr)
        sys.exit(1)

    beats_data = json.loads(beats_path.read_text(encoding="utf-8"))
    result = build_candidates(show, beats_data)

    candidates = result["candidates"]
    total = len(candidates)

    # Write report first (always)
    out_dir = Path.cwd() / "outputs" / slug / "candidates"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = _build_report(result)
    (out_dir / "candidates_report.md").write_text(report, encoding="utf-8")
    print(report)

    # Sanity gate
    if total < 60 or total > 250:
        print(
            f"\nWARNING: {total} candidates is outside the sanity gate [60, 250]. "
            "Stopping before judge.",
            file=sys.stderr,
        )
        sys.exit(0)

    # Write candidates.json
    (out_dir / "candidates.json").write_text(
        json.dumps(candidates, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {total} candidates to {out_dir / 'candidates.json'}")


if __name__ == "__main__":
    main()

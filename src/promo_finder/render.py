"""Markdown renderer for promo lists."""
from __future__ import annotations

from .timeutil import fmt_time

_HARD_CHECKS = [
    "ids_exist", "segment_same_episode", "segment_order", "no_overlap",
    "duration_20_60", "no_mid_line_cut", "hook_inside", "cliff_inside",
]
_SOFT_CHECKS = [
    "has_hook", "has_cliffhanger", "hook_in_first_3s", "cliff_in_last_5s",
]


def render_markdown(promos: list[dict], title: str) -> str:
    total = len(promos)
    valid_count = sum(1 for p in promos if p.get("checks", {}).get("valid", False))

    lines: list[str] = [f"# {title}", ""]

    # Summary header
    method = promos[0]["method"] if promos else "unknown"
    lines.append(f"Method: **{method}**")
    lines.append(f"Promos: {total}  |  Valid: {valid_count}  |  Invalid: {total - valid_count}")
    lines.append("")

    # Hard check failure counts
    lines.append("**Hard check failures:**")
    any_hard_fail = False
    for name in _HARD_CHECKS:
        fails = sum(
            1 for p in promos
            if not p.get("checks", {}).get("hard", {}).get(name, True)
        )
        if fails:
            any_hard_fail = True
            lines.append(f"- {name}: {fails} failure(s)")
    if not any_hard_fail:
        lines.append("- none")
    lines.append("")

    # Soft check pass rates
    lines.append("**Soft check pass rates:**")
    for name in _SOFT_CHECKS:
        passes = sum(
            1 for p in promos
            if p.get("checks", {}).get("soft", {}).get(name, False)
        )
        pct = 100 * passes // total if total else 0
        lines.append(f"- {name}: {passes}/{total} ({pct}%)")
    lines.append("")
    lines.append(
        "> Note: soft checks are structural — they verify that a hook *exists* in the "
        "first 3 s and a cliffhanger *exists* in the last 5 s. Quality is judged separately."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Sort by rank if present, else by promo_id
    sorted_promos = sorted(
        promos,
        key=lambda p: (p["rank"] is None, p["rank"], p["promo_id"]),
    )

    for p in sorted_promos:
        lines.append(f"## {p['promo_id']}")
        lines.append("")

        for seg in p.get("segments", []):
            ep = seg.get("episode", "?")
            s_tc = seg.get("start_tc", "?")
            e_tc = seg.get("end_tc", "?")
            dur = seg.get("duration")
            dur_str = f"{dur:.1f} s" if dur is not None else "?"
            lines.append(f"E{ep:02d}  {s_tc} → {e_tc}  ({dur_str})")

        total_dur = p.get("duration")
        lines.append(
            f"Total duration: {total_dur:.1f} s" if total_dur is not None else "Total duration: ?"
        )
        lines.append("")

        hook = p.get("hook")
        if hook:
            at = hook.get("at")
            at_str = f"{at:.2f} s" if at is not None else "?"
            lines.append(f"**Hook** (at {at_str}): \"{hook.get('text', '')}\"")
        else:
            lines.append("**Hook:** none")

        cliff = p.get("cliffhanger")
        if cliff:
            at = cliff.get("at")
            at_str = f"{at:.2f} s" if at is not None else "?"
            lines.append(f"**Cliffhanger** (at {at_str}): \"{cliff.get('text', '')}\"")
        else:
            lines.append("**Cliffhanger:** none")

        lines.append("")
        lines.append(f"Why: {p.get('why', '')}")
        lines.append("")

        checks = p.get("checks", {})
        hard = checks.get("hard", {})
        soft = checks.get("soft", {})
        hard_parts = [
            f"{'✓' if hard.get(n, False) else '✗'} {n}"
            for n in _HARD_CHECKS
        ]
        lines.append("Checks: " + "  ".join(hard_parts))
        soft_parts = [
            f"{'✓' if soft.get(n, False) else '✗'} {n}"
            for n in _SOFT_CHECKS
        ]
        lines.append("Soft:   " + "  ".join(soft_parts))

        errs = checks.get("errors", [])
        if errs:
            for e in errs:
                lines.append(f"> ✗ {e}")

        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)

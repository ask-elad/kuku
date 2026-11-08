"""Rank judged promos and produce final outputs.

CLI: python -m promo_finder.rank "<show folder>"
Input: outputs/<slug>/judge/judged.json
Outputs: outputs/<slug>/final/  +  build/<slug>/review_top10.md
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .scriptfmt import format_clip
from .show import load_show
from .timeutil import fmt_time

_SCORE_WEIGHTS = {"hook": 0.4, "cliffhanger": 0.3, "standalone": 0.3}
_SENSITIVE_PENALTY = 0.5
_TOP_N = 10
_RETARGETING_N = 5


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _weighted_score(scores: dict) -> float:
    return round(
        sum(_SCORE_WEIGHTS[f] * scores[f] for f in _SCORE_WEIGHTS),
        4,
    )


def _acquisition_score(score: float, first_episode: int, n_episodes: int) -> float:
    """Penalise late-episode promos: E01 → no penalty, last ep → −0.5."""
    if n_episodes <= 1:
        return score
    penalty = 0.5 * (first_episode - 1) / (n_episodes - 1)
    return round(score - penalty, 4)


# ---------------------------------------------------------------------------
# Overlap detection
# ---------------------------------------------------------------------------

def _segments_overlap(s1: dict, s2: dict) -> bool:
    """True if s1 and s2 (same episode) share > 50% of the shorter duration."""
    if s1.get("episode") != s2.get("episode"):
        return False
    lo = max(s1["start"], s2["start"])
    hi = min(s1["end"], s2["end"])
    intersection = max(0.0, hi - lo)
    if intersection == 0.0:
        return False
    shorter = min(s1["end"] - s1["start"], s2["end"] - s2["start"])
    return intersection > 0.5 * shorter


def _promos_overlap(p1: dict, p2: dict) -> bool:
    """True if any segment pair from p1 and p2 overlaps."""
    for s1 in p1.get("segments", []):
        for s2 in p2.get("segments", []):
            if _segments_overlap(s1, s2):
                return True
    return False


def _cluster_overlaps(promos: list[dict]) -> list[list[int]]:
    """Return connected components (by index) of the overlap graph."""
    n = len(promos)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    for i in range(n):
        for j in range(i + 1, n):
            if _promos_overlap(promos[i], promos[j]):
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(i)
    return list(groups.values())


# ---------------------------------------------------------------------------
# Text fill from show
# ---------------------------------------------------------------------------

def _block_text(show, block_id: str) -> str:
    bl = show.block(block_id)
    if bl is None:
        return ""
    text = bl["text"]
    if bl["type"] == "DIALOGUE":
        return f"{bl['label_raw']}: {text}"
    return text


# ---------------------------------------------------------------------------
# Sort key
# ---------------------------------------------------------------------------

def _sort_key(p: dict) -> tuple:
    """score desc → earlier first_ep → shorter duration → promo_id."""
    first_ep = min(
        (s.get("episode", 9999) for s in p.get("segments", []) if s.get("episode") is not None),
        default=9999,
    )
    return (-p["score"], first_ep, p.get("duration", 0.0), p["promo_id"])


def _acq_sort_key(p: dict) -> tuple:
    """acquisition_score desc → earlier first_ep → shorter duration → promo_id."""
    first_ep = min(
        (s.get("episode", 9999) for s in p.get("segments", []) if s.get("episode") is not None),
        default=9999,
    )
    return (-p["acquisition_score"], first_ep, p.get("duration", 0.0), p["promo_id"])


# ---------------------------------------------------------------------------
# Segment label for output (e.g. "E23 01:19.00–02:11.50")
# ---------------------------------------------------------------------------

def _seg_label(seg: dict) -> str:
    ep = seg.get("episode", "?")
    start_tc = seg.get("start_tc") or fmt_time(seg.get("start", 0.0))
    end_tc = seg.get("end_tc") or fmt_time(seg.get("end", 0.0))
    return f"E{ep:02d} {start_tc}–{end_tc}"


def _segments_str(promo: dict) -> str:
    return " + ".join(_seg_label(s) for s in promo.get("segments", []))


# ---------------------------------------------------------------------------
# Core ranking
# ---------------------------------------------------------------------------

def rank_promos(judged: list[dict], show) -> tuple[list[dict], list[dict]]:
    """Return ranked promos (unsafe excluded, sensitive penalised, clusters resolved).

    Main ranking uses acquisition_score (penalises late-episode promos) so that
    new-viewer promos surface first. Each promo also gets an audience field:
    "retargeting" for the top-5 late-episode promos, "acquisition" for all others.
    """
    n_episodes = max((ep["episode"] for ep in show.episodes), default=1)

    # Score + safety
    scored: list[dict] = []
    excluded: list[dict] = []

    for p in judged:
        p = dict(p)
        raw_scores = p.get("scores")
        if not raw_scores:
            p["score"] = 0.0
            p["flags"] = ["no_judgment"]
        else:
            base = _weighted_score(raw_scores)
            flags: list[str] = []
            safety_level = p.get("safety", {}).get("level", "ok")
            if safety_level == "unsafe":
                excluded.append(p)
                continue
            if safety_level == "sensitive":
                base = round(base - _SENSITIVE_PENALTY, 4)
                flags.append("needs_review")
            p["score"] = base
            p["flags"] = flags

        # Fill text fields from show
        for field in ("hook", "cliffhanger"):
            hc = p.get(field)
            if hc and hc.get("block_id"):
                hc["text"] = _block_text(show, hc["block_id"])

        scored.append(p)

    # Cluster overlaps (best-score promo wins within each cluster)
    clusters = _cluster_overlaps(scored)
    main_promos: list[dict] = []
    for group in clusters:
        members = [scored[i] for i in group]
        members.sort(key=lambda p: (-p["score"], p["promo_id"]))
        main = dict(members[0])
        alternatives = []
        for alt in members[1:]:
            alt_hook_text = (alt.get("hook") or {}).get("text", "")
            alternatives.append({
                "promo_id": alt["promo_id"],
                "score": alt["score"],
                "hook_text": alt_hook_text,
                "duration": alt.get("duration", 0.0),
            })
        main["alternatives"] = alternatives
        main_promos.append(main)

    # Compute acquisition_score and audience (by series position) for each main promo
    ret_threshold = int(2 / 3 * n_episodes)
    for p in main_promos:
        first_ep = min(
            (s.get("episode", 9999) for s in p.get("segments", []) if s.get("episode") is not None),
            default=9999,
        )
        p["acquisition_score"] = _acquisition_score(p["score"], first_ep, n_episodes)
        p["audience"] = "retargeting" if first_ep > ret_threshold else "acquisition"

    # Split into exclusive pools
    acq_pool = sorted(
        [p for p in main_promos if p["audience"] == "acquisition"],
        key=_acq_sort_key,
    )
    ret_pool = [p for p in main_promos if p["audience"] == "retargeting"]

    # New-viewer top 10: acquisition-only, by acquisition_score, one per starting episode
    top10: list[dict] = []
    seen_acq_ep: set[int] = set()
    rest_acq: list[dict] = []
    for p in acq_pool:
        first_ep = min(
            (s.get("episode", 9999) for s in p.get("segments", []) if s.get("episode") is not None),
            default=9999,
        )
        if len(top10) < _TOP_N and first_ep not in seen_acq_ep:
            top10.append(p)
            seen_acq_ep.add(first_ep)
        else:
            rest_acq.append(p)

    # Ranks 11+: remaining acquisition + all retargeting, by acquisition_score
    rest_all = sorted(rest_acq + ret_pool, key=_acq_sort_key)

    ranked = top10 + rest_all
    for i, p in enumerate(ranked):
        p["rank"] = i + 1

    return ranked, excluded


# ---------------------------------------------------------------------------
# Format helpers for outputs
# ---------------------------------------------------------------------------

def _fmt_duration(secs: float) -> str:
    return f"{secs:.1f}s"


def _scores_line(p: dict) -> str:
    s = p.get("scores", {})
    acq = p.get("acquisition_score")
    acq_str = f"  acq={acq:.2f}" if acq is not None else ""
    return (
        f"hook={s.get('hook', '?')} "
        f"cliff={s.get('cliffhanger', '?')} "
        f"stand={s.get('standalone', '?')} "
        f"→ **{p.get('score', 0.0):.2f}**{acq_str}"
    )


# ---------------------------------------------------------------------------
# promos.json
# ---------------------------------------------------------------------------

def _build_promos_json(ranked: list[dict]) -> list[dict]:
    out = []
    for p in ranked:
        entry = {
            "rank": p["rank"],
            "promo_id": p["promo_id"],
            "segments": p.get("segments", []),
            "duration": p.get("duration", 0.0),
            "hook": p.get("hook", {}),
            "cliffhanger": p.get("cliffhanger", {}),
            "scores": p.get("scores", {}),
            "score": p.get("score", 0.0),
            "acquisition_score": p.get("acquisition_score", p.get("score", 0.0)),
            "audience": p.get("audience", "acquisition"),
            "safety": p.get("safety", {}),
            "flags": p.get("flags", []),
            "confusions": p.get("confusions", []),
            "why": p.get("why", ""),
            "alternatives": p.get("alternatives", []),
        }
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# promos.csv
# ---------------------------------------------------------------------------

def _build_promos_csv(ranked: list[dict]) -> str:
    fieldnames = [
        "rank", "promo_id", "segments", "duration", "score", "acquisition_score",
        "audience", "hook", "cliffhanger", "standalone",
        "safety", "hook_text", "cliffhanger_text", "why",
    ]
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for p in ranked:
        s = p.get("scores", {})
        writer.writerow({
            "rank": p["rank"],
            "promo_id": p["promo_id"],
            "segments": _segments_str(p),
            "duration": f"{p.get('duration', 0.0):.1f}",
            "score": f"{p.get('score', 0.0):.2f}",
            "acquisition_score": f"{p.get('acquisition_score', p.get('score', 0.0)):.4f}",
            "audience": p.get("audience", "acquisition"),
            "hook": s.get("hook", ""),
            "cliffhanger": s.get("cliffhanger", ""),
            "standalone": s.get("standalone", ""),
            "safety": p.get("safety", {}).get("level", "ok"),
            "hook_text": (p.get("hook") or {}).get("text", ""),
            "cliffhanger_text": (p.get("cliffhanger") or {}).get("text", ""),
            "why": p.get("why", ""),
        })
    return buf.getvalue()


# ---------------------------------------------------------------------------
# promos.md
# ---------------------------------------------------------------------------

def _build_promos_md(
    ranked: list[dict],
    show_title: str,
    model: str,
    date: str,
    spend: str,
) -> str:
    lines: list[str] = []

    # Header
    lines.append(f"# Promos — {show_title}\n")
    lines.append(f"Model: {model}  |  Date: {date}  |  Promos: {len(ranked)}  |  Spend: {spend}\n")

    top10 = [p for p in ranked if p["rank"] <= _TOP_N]
    retargeting = [p for p in ranked if p.get("audience") == "retargeting"]

    # Top 10 table (acquisition — new viewers)
    lines.append("## Post these first: new viewers (top 10)\n")
    lines.append("| Rank | Segments | Duration | Score | Acq Score | Hook | Why | Flags |")
    lines.append("|------|----------|----------|-------|-----------|------|-----|-------|")
    for p in top10:
        hook_text = (p.get("hook") or {}).get("text", "")
        flags = ", ".join(p.get("flags", [])) or "—"
        acq = p.get("acquisition_score", p.get("score", 0.0))
        lines.append(
            f"| {p['rank']} | {_segments_str(p)} | {_fmt_duration(p.get('duration', 0.0))} "
            f"| {p.get('score', 0.0):.2f} | {acq:.4f} "
            f"| {hook_text[:60]} | {p.get('why', '')[:80]} | {flags} |"
        )
    lines.append("")

    # Retargeting top 5 — one per starting episode
    lines.append("## For existing viewers: retargeting (top 5)\n")
    if retargeting:
        lines.append("| Rank | Segments | Duration | Score | Hook | Why |")
        lines.append("|------|----------|----------|-------|------|-----|")
        seen_ret_ep: set[int] = set()
        ret_display: list[dict] = []
        for p in sorted(retargeting, key=lambda x: (-x.get("score", 0.0), x["promo_id"])):
            first_ep = min(
                (s.get("episode", 9999) for s in p.get("segments", [])
                 if s.get("episode") is not None),
                default=9999,
            )
            if len(ret_display) < _RETARGETING_N and first_ep not in seen_ret_ep:
                ret_display.append(p)
                seen_ret_ep.add(first_ep)
        for p in ret_display:
            hook_text = (p.get("hook") or {}).get("text", "")
            lines.append(
                f"| {p['rank']} | {_segments_str(p)} | {_fmt_duration(p.get('duration', 0.0))} "
                f"| {p.get('score', 0.0):.2f} | {hook_text[:60]} | {p.get('why', '')[:80]} |"
            )
    else:
        lines.append("_(none — no promos from the last third of the series)_")
    lines.append("")

    # Why these first
    lines.append("## Why these first\n")
    lines.append(
        "1. **Hook-weighted score** (0.4 × hook + 0.3 × cliffhanger + 0.3 × standalone) ranks every promo."
    )
    lines.append(
        "2. **Acquisition score** = score − 0.5 × (episode − 1) / (total − 1): "
        "late-episode promos are penalised because new viewers have not watched 40+ episodes "
        "of context, and late payoffs spoil the story's endgame."
    )
    lines.append(
        "3. **One per episode** in the top 10: variety across episodes maximises reach."
    )
    lines.append(
        "4. **Ties** resolve by earlier starting episode then shorter duration.\n"
    )

    # All promos
    lines.append("## All Promos\n")
    for p in ranked:
        hook_text = (p.get("hook") or {}).get("text", "")
        cliff_text = (p.get("cliffhanger") or {}).get("text", "")
        hook_at = (p.get("hook") or {}).get("at")
        hook_at_str = f" at {fmt_time(hook_at)}" if hook_at is not None else ""
        flags_str = f"  `{'  '.join(p.get('flags', []))}`" if p.get("flags") else ""

        lines.append(f"### #{p['rank']} — {p['promo_id']}{flags_str}")
        lines.append(f"**Segments**: {_segments_str(p)}  |  **Duration**: {_fmt_duration(p.get('duration', 0.0))}")
        lines.append(f"**Scores**: {_scores_line(p)}")
        lines.append(f"**Hook** ({hook_at_str.strip()}): \"{hook_text}\"")
        lines.append(f"**Cliffhanger**: \"{cliff_text}\"")
        lines.append(f"**Why**: {p.get('why', '')}")
        confusions = p.get("confusions", [])
        if confusions:
            lines.append(f"**Confusions**: {'; '.join(confusions)}")
        alts = p.get("alternatives", [])
        if alts:
            alt_strs = [
                f"{a['promo_id']} (score={a['score']:.2f}, {_fmt_duration(a['duration'])})"
                for a in alts
            ]
            lines.append(f"**Alternative cuts**: {', '.join(alt_strs)}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ranking_report.md
# ---------------------------------------------------------------------------

def _old_top10_by_score(ranked: list[dict]) -> list[dict]:
    """Re-derive the pre-task top 10 using raw score (no acquisition penalty)."""
    sorted_by_score = sorted(ranked, key=_sort_key)
    seen_eps: set[int] = set()
    top10: list[dict] = []
    for p in sorted_by_score:
        first_ep = min(
            (s.get("episode", 9999) for s in p.get("segments", []) if s.get("episode") is not None),
            default=9999,
        )
        if len(top10) < _TOP_N and first_ep not in seen_eps:
            top10.append(p)
            seen_eps.add(first_ep)
    return top10


def _build_ranking_report(
    ranked: list[dict],
    excluded: list[dict],
    judged_baseline: list[dict],
    calibration_data: dict | None,
    show_title: str,
) -> str:
    lines: list[str] = [f"# Ranking Report — {show_title}\n"]

    # Score distribution
    lines.append("## Score Distribution (main promos)\n")
    scores_all = [p["score"] for p in ranked]
    if scores_all:
        lines.append(f"- Count: {len(scores_all)}")
        lines.append(f"- Min: {min(scores_all):.2f}  Max: {max(scores_all):.2f}  "
                     f"Mean: {sum(scores_all)/len(scores_all):.2f}")
        buckets: dict[str, int] = {}
        for s in scores_all:
            b = f"{s:.1f}"
            buckets[b] = buckets.get(b, 0) + 1
        dist = "  ".join(f"{k}→{v}" for k, v in sorted(buckets.items()))
        lines.append(f"- Distribution: {dist}")
    lines.append("")

    # Overlap clusters
    all_scored = [p for p in ranked] + [
        dict(a, promo_id=a["promo_id"], score=a["score"],
             segments=[], duration=a["duration"])
        for p in ranked for a in p.get("alternatives", [])
    ]
    cluster_sizes: list[int] = [1 + len(p.get("alternatives", [])) for p in ranked]
    multi = [s for s in cluster_sizes if s > 1]
    lines.append("## Overlap Clusters\n")
    lines.append(f"- Total clusters: {len(cluster_sizes)}")
    lines.append(f"- Multi-promo clusters: {len(multi)} (sizes: {sorted(multi, reverse=True) or '—'})")
    lines.append("")

    # Pipeline vs baseline
    ranked_pipeline = ranked
    top10_pipeline = [p for p in ranked if p["rank"] <= _TOP_N]

    def _mean(lst: list[float]) -> str:
        return f"{sum(lst)/len(lst):.2f}" if lst else "n/a"

    def _mean_field(promos: list[dict], field: str) -> str:
        vals = [p["scores"][field] for p in promos if p.get("scores", {}).get(field) is not None]
        return _mean(vals)

    bl_scored = [p for p in judged_baseline if p.get("scores")]
    bl_ranked = sorted(bl_scored, key=lambda p: -_weighted_score(p.get("scores", {})))
    top10_baseline = bl_ranked[:_TOP_N]

    lines.append("## Pipeline vs Baseline\n")
    lines.append("### All judged promos\n")
    lines.append("| Group    | n  | hook | cliffhanger | standalone | score |")
    lines.append("|----------|----|------|-------------|------------|-------|")
    for label, group in [("Pipeline", ranked_pipeline), ("Baseline", bl_scored)]:
        score_mean = _mean([p["score"] for p in group if "score" in p]) if label == "Pipeline" else \
                     _mean([_weighted_score(p["scores"]) for p in group])
        lines.append(
            f"| {label:<8} | {len(group):<2} | "
            f"{_mean_field(group, 'hook'):<4} | "
            f"{_mean_field(group, 'cliffhanger'):<11} | "
            f"{_mean_field(group, 'standalone'):<10} | "
            f"{score_mean:<5} |"
        )
    lines.append("")

    lines.append("### Top 10 of each\n")
    lines.append("| Group    | n  | hook | cliffhanger | standalone | score |")
    lines.append("|----------|----|------|-------------|------------|-------|")
    for label, group in [("Pipeline", top10_pipeline), ("Baseline", top10_baseline)]:
        score_mean = _mean([p["score"] for p in group if "score" in p]) if label == "Pipeline" else \
                     _mean([_weighted_score(p["scores"]) for p in group])
        lines.append(
            f"| {label:<8} | {len(group):<2} | "
            f"{_mean_field(group, 'hook'):<4} | "
            f"{_mean_field(group, 'cliffhanger'):<11} | "
            f"{_mean_field(group, 'standalone'):<10} | "
            f"{score_mean:<5} |"
        )
    lines.append("")

    # Calibration
    if calibration_data:
        summary = calibration_data.get("summary", {})
        lines.append("### Mixed-batch calibration\n")
        lines.append(
            f"6 batches × 8 clips (4 pipeline + 4 baseline, seed={calibration_data.get('seed', 7)})\n"
        )
        lines.append("| Group    | n  | hook | cliffhanger | standalone |")
        lines.append("|----------|----|------|-------------|------------|")
        for group in ("pipeline", "baseline"):
            m = summary.get(group, {})
            n = m.get("n", 0)

            def _sf(key: str) -> str:
                v = m.get(key)
                return f"{v:.2f}" if v is not None else "n/a"

            lines.append(
                f"| {group.capitalize():<8} | {n:<2} | "
                f"{_sf('hook'):<4} | "
                f"{_sf('cliffhanger'):<11} | "
                f"{_sf('standalone'):<10} |"
            )
        lines.append("")

    # Sensitive / unsafe
    sensitive = [p for p in ranked if "needs_review" in p.get("flags", [])]
    unsafe_list = excluded

    lines.append("## Safety\n")
    lines.append(f"- Sensitive (needs_review): {len(sensitive)}")
    if sensitive:
        lines.append("  " + ", ".join(p["promo_id"] for p in sensitive))
    lines.append(f"- Unsafe (excluded): {len(unsafe_list)}")
    if unsafe_list:
        lines.append("  " + ", ".join(p["promo_id"] for p in unsafe_list))
    lines.append("")

    # New top 10 (acquisition_score) vs old top 10 (raw score)
    new_top10 = [p for p in ranked if p["rank"] <= _TOP_N]
    old_top10 = _old_top10_by_score(ranked)
    new_ids = {p["promo_id"] for p in new_top10}
    old_ids = {p["promo_id"] for p in old_top10}
    moved_in = new_ids - old_ids
    moved_out = old_ids - new_ids

    lines.append("## New top 10 vs old top 10 (acquisition_score vs raw score)\n")
    lines.append("| # | New top 10 (acq) | Acq score | # | Old top 10 (score) | Score |")
    lines.append("|---|-----------------|-----------|---|-------------------|-------|")
    for i in range(max(len(new_top10), len(old_top10))):
        new_p = new_top10[i] if i < len(new_top10) else None
        old_p = old_top10[i] if i < len(old_top10) else None
        new_cell = (
            f"{'→ ' if new_p['promo_id'] in moved_in else ''}{new_p['promo_id']}"
            if new_p else ""
        )
        old_cell = (
            f"{'← ' if old_p['promo_id'] in moved_out else ''}{old_p['promo_id']}"
            if old_p else ""
        )
        new_acq = f"{new_p.get('acquisition_score', 0.0):.4f}" if new_p else ""
        old_score = f"{old_p.get('score', 0.0):.2f}" if old_p else ""
        lines.append(
            f"| {i+1} | {new_cell} | {new_acq} | {i+1} | {old_cell} | {old_score} |"
        )
    lines.append("")
    lines.append(f"**Moved in** (new viewers): {', '.join(sorted(moved_in)) or '—'}")
    lines.append(f"**Moved out** (demoted by episode penalty): {', '.join(sorted(moved_out)) or '—'}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# review_top10.md (Part D — not committed)
# ---------------------------------------------------------------------------

def _build_review_sheet(top10: list[dict], show) -> str:
    lines: list[str] = ["# Human Review — Top 10 Promos\n"]
    for p in top10:
        lines.append(f"## #{p['rank']} — {p['promo_id']}")
        lines.append(f"**Segments**: {_segments_str(p)}\n")
        lines.append("```")
        lines.append(format_clip(p, show, redact=False))
        lines.append("```\n")
        lines.append("- [ ] Hook lands in first 3 s (would I stop scrolling?)")
        lines.append("- [ ] Ends on an unresolved moment (do I need to know what happens next?)")
        lines.append("- [ ] Makes sense to a stranger")
        lines.append("- [ ] Start/end cut points are clean (no half sentence, no dead air)")
        lines.append("- [ ] I'd post this.   Notes:\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Rank judged promos and write final outputs.")
    parser.add_argument("show_dir", type=Path, metavar="show_folder")
    parser.add_argument("--spend", type=str, default="",
                        help="Total spend string to embed in promos.md header")
    args = parser.parse_args()

    show = load_show(args.show_dir)
    slug = show.slug

    judge_dir = Path.cwd() / "outputs" / slug / "judge"
    judged_path = judge_dir / "judged.json"
    judged_bl_path = judge_dir / "judged_baseline.json"
    cal_path = judge_dir / "calibration.json"

    if not judged_path.exists():
        print(f"ERROR: {judged_path} not found", file=sys.stderr)
        sys.exit(1)

    judged: list[dict] = json.loads(judged_path.read_text(encoding="utf-8"))
    judged_baseline: list[dict] = (
        json.loads(judged_bl_path.read_text(encoding="utf-8"))
        if judged_bl_path.exists()
        else []
    )
    calibration_data: dict | None = (
        json.loads(cal_path.read_text(encoding="utf-8"))
        if cal_path.exists()
        else None
    )

    ranked, excluded = rank_promos(judged, show)

    # Spend
    if not args.spend:
        from . import llm as _llm
        import csv as _csv
        try:
            total = 0.0
            with _llm._LOG_PATH.open(encoding="utf-8") as f:
                for row in _csv.DictReader(f):
                    cost_str = row.get("cost_usd", "")
                    if cost_str:
                        total += float(cost_str)
            spend_str = f"${total:.4f}"
        except Exception:
            spend_str = args.spend or "unknown"
    else:
        spend_str = args.spend

    # Determine model from env
    import os
    from dotenv import load_dotenv
    load_dotenv()
    model_str = os.environ.get("LLM_MODEL", "unknown")

    from datetime import date as _date
    date_str = _date.today().isoformat()

    # Final outputs dir
    final_dir = Path.cwd() / "outputs" / slug / "final"
    final_dir.mkdir(parents=True, exist_ok=True)

    # promos.json
    (final_dir / "promos.json").write_text(
        json.dumps(_build_promos_json(ranked), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # promos.csv
    (final_dir / "promos.csv").write_text(
        _build_promos_csv(ranked), encoding="utf-8"
    )

    # promos.md
    (final_dir / "promos.md").write_text(
        _build_promos_md(ranked, show.title, model_str, date_str, spend_str),
        encoding="utf-8",
    )

    # ranking_report.md
    (final_dir / "ranking_report.md").write_text(
        _build_ranking_report(ranked, excluded, judged_baseline, calibration_data, show.title),
        encoding="utf-8",
    )

    # review_top10.md (build/, not committed)
    build_dir = Path.cwd() / "build" / slug
    build_dir.mkdir(parents=True, exist_ok=True)
    top10 = [p for p in ranked if p["rank"] <= _TOP_N]
    (build_dir / "review_top10.md").write_text(
        _build_review_sheet(top10, show), encoding="utf-8"
    )

    print(f"Final outputs written to {final_dir}/")
    print(f"Review sheet: {build_dir}/review_top10.md")
    print(f"Spend: {spend_str}")
    print(f"Ranked {len(ranked)} promos ({len(excluded)} excluded as unsafe)")


if __name__ == "__main__":
    main()

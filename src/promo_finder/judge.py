"""Judge candidate promo clips with a cold-viewer LLM.

CLI: python -m promo_finder.judge "<show folder>" [--limit-batches N]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

from .show import load_show
from .scriptfmt import format_clip
from . import llm as _llm

_BATCH_SIZE = 8
_LABELS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_SAFETY_ORDER = {"ok": 0, "sensitive": 1, "unsafe": 2}


# ---------------------------------------------------------------------------
# Clip text builder
# ---------------------------------------------------------------------------

def _build_clips_text(batch: list[tuple[str, dict]], show) -> str:
    """Return the {{clips}} value: ### CLIP A\n<text>\n\n### CLIP B\n..."""
    parts: list[str] = []
    for label, promo in batch:
        clip_text = format_clip(promo, show)
        parts.append(f"### CLIP {label}\n{clip_text}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Response validation
# ---------------------------------------------------------------------------

def _validate_response(response: dict, expected_labels: list[str]) -> dict[str, dict]:
    """Validate the judge response. Returns label -> entry dict for valid entries.

    Bad or missing entries are omitted from the result.
    """
    clips = response.get("clips")
    if not isinstance(clips, list):
        return {}

    seen: dict[str, dict] = {}
    for entry in clips:
        if not isinstance(entry, dict):
            continue
        label = entry.get("label")
        if not isinstance(label, str):
            continue
        # Dedup: if label appears twice, discard both (treat as error)
        if label in seen:
            seen[label] = {}  # mark as bad
            continue
        seen[label] = entry

    valid: dict[str, dict] = {}
    for label in expected_labels:
        entry = seen.get(label)
        if not entry:
            continue  # missing or duplicated

        # Check scores
        ok = True
        for field in ("hook", "cliffhanger", "standalone"):
            val = entry.get(field)
            if not isinstance(val, int) or not (1 <= val <= 5):
                ok = False
                break

        if not ok:
            continue

        # Check safety
        safety = entry.get("safety")
        if safety not in _SAFETY_ORDER:
            continue

        # Check confusions is a list
        if not isinstance(entry.get("confusions", []), list):
            continue

        valid[label] = entry

    # Also reject if any extra labels appear
    for label in seen:
        if label not in expected_labels:
            # extra label: invalidate everything (treat batch as bad)
            # Actually per spec: a bad entry → that clip has no judgment; an extra
            # label means the response has an unexpected entry — just ignore it.
            pass

    return valid


# ---------------------------------------------------------------------------
# Judge a list of promos (candidates or baselines)
# ---------------------------------------------------------------------------

def run_judge(
    promos: list[dict],
    show,
    *,
    limit_batches: int | None = None,
    round1_seed: int = 1,
    round2_seed: int = 2,
    id_field: str = "promo_id",
    tag_prefix: str = "judge",
) -> tuple[list[dict], list[dict]]:
    """Judge all promos in two rounds.

    Returns (raw_batches, judged_promos).
    raw_batches: list of dicts with round/batch/label_map/result.
    judged_promos: promos with scores/safety/confusions/why/judge_rounds added.
    """
    promo_map: dict[str, dict] = {p[id_field]: p for p in promos}
    ids = [p[id_field] for p in promos]

    raw_batches: list[dict] = []
    # round_results[promo_id][round_index] = validated entry dict | None
    round_results: dict[str, list[dict | None]] = {pid: [None, None] for pid in ids}

    for round_idx, seed in enumerate([round1_seed, round2_seed]):
        rng = random.Random(seed)
        shuffled = list(ids)
        rng.shuffle(shuffled)

        batches = [
            shuffled[i: i + _BATCH_SIZE]
            for i in range(0, len(shuffled), _BATCH_SIZE)
        ]

        for b_idx, batch_ids in enumerate(batches):
            if limit_batches is not None and round_idx == 0 and b_idx >= limit_batches:
                break
            if limit_batches is not None and round_idx > 0:
                break

            labels = _LABELS[: len(batch_ids)]
            label_map = {label: pid for label, pid in zip(labels, batch_ids)}
            tag = f"{tag_prefix}:r{round_idx + 1}:b{b_idx + 1:02d}"

            batch_promos = [(label, promo_map[pid]) for label, pid in zip(labels, batch_ids)]
            clips_text = _build_clips_text(batch_promos, show)

            try:
                response = _llm.complete_json("judge", {"clips": clips_text}, tag=tag)
                validated = _validate_response(response, labels)
                raw_batches.append({
                    "round": round_idx + 1,
                    "batch": b_idx + 1,
                    "label_map": label_map,
                    "result": {"clips": {lb: validated.get(lb) for lb in labels}},
                })
                for label, pid in zip(labels, batch_ids):
                    entry = validated.get(label)
                    if entry:
                        round_results[pid][round_idx] = entry

            except _llm.LLMError as exc:
                raw_batches.append({
                    "round": round_idx + 1,
                    "batch": b_idx + 1,
                    "label_map": label_map,
                    "result": {"error": str(exc)},
                })

    # Combine two rounds per promo
    judged: list[dict] = []
    for promo in promos:
        pid = promo[id_field]
        r1, r2 = round_results[pid]
        p = dict(promo)

        valid_rounds = [r for r in [r1, r2] if r is not None]
        p["judge_rounds"] = len(valid_rounds)

        if not valid_rounds:
            judged.append(p)
            continue

        # Scores: mean of valid rounds
        scores: dict[str, float] = {}
        for field in ("hook", "cliffhanger", "standalone"):
            vals = [r[field] for r in valid_rounds]
            scores[field] = round(sum(vals) / len(vals), 1)
        p["scores"] = scores

        # Disagreement: max abs diff across three scores between rounds
        if r1 and r2:
            diffs = [abs(r1[f] - r2[f]) for f in ("hook", "cliffhanger", "standalone")]
            p["judge_disagreement"] = max(diffs)
        else:
            p["judge_disagreement"] = None

        # Safety: worst of rounds
        def _safety_level(r: dict) -> int:
            return _SAFETY_ORDER.get(r.get("safety", "ok"), 0)

        worst_round = max(valid_rounds, key=_safety_level)
        p["safety"] = {
            "level": worst_round.get("safety", "ok"),
            "reason": worst_round.get("safety_reason", ""),
        }

        # Confusions: union deduplicated, max 4
        seen_conf: list[str] = []
        for r in valid_rounds:
            for c in r.get("confusions", [])[:3]:
                if c not in seen_conf:
                    seen_conf.append(c)
        p["confusions"] = seen_conf[:4]

        # Why and hook_moment: round 1 if valid, else round 2
        primary = r1 if r1 else r2
        p["why"] = primary.get("why", "")  # type: ignore[union-attr]
        p["hook_moment"] = primary.get("hook_moment", "")  # type: ignore[union-attr]

        judged.append(p)

    return raw_batches, judged


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _build_report(
    judged: list[dict],
    raw_batches: list[dict],
    judged_baseline: list[dict] | None = None,
) -> str:
    lines: list[str] = ["# Judge Report\n"]

    # 1. Coverage
    rounds_2 = sum(1 for p in judged if p.get("judge_rounds") == 2)
    rounds_1 = sum(1 for p in judged if p.get("judge_rounds") == 1)
    rounds_0 = sum(1 for p in judged if p.get("judge_rounds") == 0)
    batch_errors = sum(1 for b in raw_batches if "error" in b.get("result", {}))
    lines.append("## Coverage\n")
    lines.append(f"- 2 rounds: {rounds_2}")
    lines.append(f"- 1 round:  {rounds_1}")
    lines.append(f"- 0 rounds: {rounds_0}")
    lines.append(f"- Batch errors: {batch_errors}\n")

    # 2. Score distributions
    judged_scored = [p for p in judged if p.get("judge_rounds", 0) > 0]
    lines.append("## Score Distributions\n")
    for field in ("hook", "cliffhanger", "standalone"):
        counts = defaultdict(int)
        for p in judged_scored:
            s = p.get("scores", {}).get(field)
            if s is not None:
                bucket = round(s)
                counts[bucket] += 1
        dist = "  ".join(f"{k}→{counts[k]}" for k in sorted(counts))
        lines.append(f"- **{field}**: {dist}")
    lines.append("")

    # 3. Consistency
    disagreements = [
        p["judge_disagreement"]
        for p in judged_scored
        if p.get("judge_rounds") == 2 and p.get("judge_disagreement") is not None
    ]
    if disagreements:
        mean_dis = sum(disagreements) / len(disagreements)
        pct_ge2 = 100 * sum(1 for d in disagreements if d >= 2) / len(disagreements)
        lines.append("## Judge Consistency\n")
        lines.append(f"- Mean disagreement: {mean_dis:.2f}")
        lines.append(f"- % clips with disagreement ≥ 2: {pct_ge2:.1f}%\n")

    # 4. Safety
    unsafe_ids = [p["promo_id"] for p in judged_scored
                  if p.get("safety", {}).get("level") == "unsafe"]
    sensitive_ids = [p["promo_id"] for p in judged_scored
                     if p.get("safety", {}).get("level") == "sensitive"]
    ok_count = len(judged_scored) - len(unsafe_ids) - len(sensitive_ids)
    lines.append("## Safety\n")
    lines.append(f"- ok: {ok_count}  sensitive: {len(sensitive_ids)}  unsafe: {len(unsafe_ids)}")
    if unsafe_ids:
        lines.append(f"- Unsafe: {', '.join(unsafe_ids)}")
    if sensitive_ids:
        lines.append(f"- Sensitive: {', '.join(sensitive_ids)}")
    lines.append("")

    # 5. Single vs bridge scores
    singles = [p for p in judged_scored if len(p.get("segments", [])) == 1]
    bridges = [p for p in judged_scored if len(p.get("segments", [])) > 1]

    def _mean_score(ps: list[dict], field: str) -> str:
        vals = [p["scores"][field] for p in ps if p.get("scores", {}).get(field) is not None]
        return f"{sum(vals) / len(vals):.2f}" if vals else "n/a"

    lines.append("## Single vs Bridge\n")
    lines.append(f"| Type   | n  | hook | cliffhanger | standalone |")
    lines.append(f"|--------|----|------|-------------|------------|")
    for label, group in [("Single", singles), ("Bridge", bridges)]:
        lines.append(
            f"| {label:<6} | {len(group):<2} | "
            f"{_mean_score(group, 'hook'):<4} | "
            f"{_mean_score(group, 'cliffhanger'):<11} | "
            f"{_mean_score(group, 'standalone'):<10} |"
        )
    lines.append("")

    # 6. Baseline comparison
    if judged_baseline:
        bl_scored = [p for p in judged_baseline if p.get("judge_rounds", 0) > 0]
        lines.append("## Baseline Comparison\n")
        lines.append("| Group    | n  | hook | cliffhanger | standalone |")
        lines.append("|----------|----|------|-------------|------------|")
        for label, group in [("Pipeline", judged_scored), ("Baseline", bl_scored)]:
            lines.append(
                f"| {label:<8} | {len(group):<2} | "
                f"{_mean_score(group, 'hook'):<4} | "
                f"{_mean_score(group, 'cliffhanger'):<11} | "
                f"{_mean_score(group, 'standalone'):<10} |"
            )
        lines.append("")

    # 7. Token / cost summary
    lines.append("## Token Usage\n")
    all_batches_summary = f"{len(raw_batches)} batches, {batch_errors} errors"
    lines.append(f"- Batches: {all_batches_summary}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Judge candidate promo clips.")
    parser.add_argument("show_dir", type=Path, metavar="show_folder")
    parser.add_argument("--limit-batches", type=int, default=None,
                        help="Limit to N batches of round 1 only (pilot mode)")
    args = parser.parse_args()

    show = load_show(args.show_dir)
    slug = show.slug

    # Load candidates
    cands_path = Path.cwd() / "outputs" / slug / "candidates" / "candidates.json"
    if not cands_path.exists():
        print(f"ERROR: candidates.json not found at {cands_path}", file=sys.stderr)
        sys.exit(1)

    candidates: list[dict] = json.loads(cands_path.read_text(encoding="utf-8"))

    out_dir = Path.cwd() / "outputs" / slug / "judge"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Judge candidates
    raw_batches, judged = run_judge(
        candidates, show, limit_batches=args.limit_batches
    )

    # Baseline (only run if not limiting)
    judged_baseline: list[dict] | None = None
    baseline_raw: list[dict] = []
    if args.limit_batches is None:
        bl_path = Path.cwd() / "outputs" / slug / "baseline" / "promos.json"
        if bl_path.exists():
            baseline_promos: list[dict] = json.loads(bl_path.read_text(encoding="utf-8"))
            baseline_raw, judged_baseline = run_judge(
                baseline_promos, show, tag_prefix="judge_baseline"
            )

    # Outputs
    all_raw = raw_batches + baseline_raw
    (out_dir / "judgments_raw.json").write_text(
        json.dumps(all_raw, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    (out_dir / "judged.json").write_text(
        json.dumps(judged, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    report = _build_report(judged, raw_batches, judged_baseline)
    (out_dir / "judge_report.md").write_text(report, encoding="utf-8")

    print(report)

    if args.limit_batches is not None:
        print("\n--- PILOT: stopped after limit-batches ---")
        # Print the first clip text for review
        if raw_batches:
            b = raw_batches[0]
            lmap = b["label_map"]
            first_label = next(iter(lmap))
            first_pid = lmap[first_label]
            first_promo = next(p for p in candidates if p["promo_id"] == first_pid)
            print(f"\nFirst clip in batch 1 ({first_label} = {first_pid}):")
            print(format_clip(first_promo, show))
            print(f"\nRaw response: {json.dumps(b['result'], indent=2)}")


if __name__ == "__main__":
    main()

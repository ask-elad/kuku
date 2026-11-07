"""AI beats detector: marks hook and cliffhanger moments per episode.

CLI: python -m promo_finder.beats "<show folder>" [--episodes 1,7,23]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

from .llm import LLMError, LLMQuotaExhausted, complete_json
from .parse import make_slug
from .scriptfmt import format_blocks
from .show import load_show
from .timeutil import fmt_time

HOOK_TYPES = {
    "slap_or_violence", "reveal", "shocking_line", "humiliation",
    "threat", "romance", "rescue", "action", "other",
}
_EPS = 0.05
_MAX_LOOKBACK = 3.0
_REPO_ROOT = Path(__file__).parent.parent.parent
_LOG_PATH = _REPO_ROOT / "logs" / "llm_usage.csv"


# ---------------------------------------------------------------------------
# Clean-start finder
# ---------------------------------------------------------------------------

def _find_clean_start(hook_start: float, ep_blocks: list[dict]) -> float | None:
    """Latest clean cut point at or before hook_start, within 3.0 s. None if none."""
    low = hook_start - _MAX_LOOKBACK
    candidates: set[float] = {hook_start}
    for bl in ep_blocks:
        if low <= bl["start"] <= hook_start:
            candidates.add(bl["start"])
        if low <= bl["end"] <= hook_start:
            candidates.add(bl["end"])

    for t in sorted(candidates, reverse=True):
        clean = all(
            not (bl["type"] == "DIALOGUE" and bl["start"] + _EPS < t < bl["end"] - _EPS)
            for bl in ep_blocks
        )
        if clean:
            return t
    return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_response(
    raw: dict, ep_num: int, block_ids_in_ep: set[str]
) -> tuple[dict, list[str]]:
    """Validate the LLM response dict.

    Returns (validated_dict, error_list).
    validated_dict has keys: hooks, cliffhangers, ending,
    _invalid_item, _invalid_id, _total_ids_returned.
    """
    errors: list[str] = []
    invalid_item = 0
    invalid_id = 0
    all_ids: list[str] = []

    hooks_raw = raw.get("hooks")
    cliffs_raw = raw.get("cliffhangers")
    ending_raw = raw.get("ending")

    if not isinstance(hooks_raw, list):
        errors.append(
            f"E{ep_num:02d}: 'hooks' missing or not a list "
            f"(got {type(hooks_raw).__name__})"
        )
        hooks_raw = []
    if not isinstance(cliffs_raw, list):
        errors.append(
            f"E{ep_num:02d}: 'cliffhangers' missing or not a list "
            f"(got {type(cliffs_raw).__name__})"
        )
        cliffs_raw = []
    if not isinstance(ending_raw, dict):
        errors.append(
            f"E{ep_num:02d}: 'ending' missing or not an object "
            f"(got {type(ending_raw).__name__})"
        )
        ending_raw = {}

    # Collect all block_ids returned (for the made-up ID rate denominator)
    for item in list(hooks_raw) + list(cliffs_raw):
        if isinstance(item, dict):
            bid = item.get("block_id")
            if isinstance(bid, str) and bid:
                all_ids.append(bid)

    def _validate_hook(item: object) -> tuple[dict | None, str]:
        """Return (cleaned_item, reason_if_bad). reason '' = good."""
        if not isinstance(item, dict):
            return None, "not a dict"
        bid = item.get("block_id")
        if not isinstance(bid, str) or not bid:
            return None, "block_id missing or not a string"
        htype = item.get("type")
        if not isinstance(htype, str) or htype not in HOOK_TYPES:
            return None, f"type {htype!r} not in allowed list"
        sp = item.get("stop_power")
        if not isinstance(sp, int) or not (1 <= sp <= 5):
            return None, f"stop_power {sp!r} not int 1-5"
        if not isinstance(item.get("why"), str):
            return None, "why missing or not a string"
        return item, ""

    def _validate_cliff(item: object) -> tuple[dict | None, str]:
        if not isinstance(item, dict):
            return None, "not a dict"
        bid = item.get("block_id")
        if not isinstance(bid, str) or not bid:
            return None, "block_id missing or not a string"
        tension = item.get("tension")
        if not isinstance(tension, int) or not (1 <= tension <= 5):
            return None, f"tension {tension!r} not int 1-5"
        if not isinstance(item.get("open_question"), str):
            return None, "open_question missing or not a string"
        return item, ""

    seen_hook_ids: set[str] = set()
    valid_hooks: list[dict] = []
    for item in hooks_raw:
        cleaned, reason = _validate_hook(item)
        if cleaned is None:
            invalid_item += 1
            continue
        bid = cleaned["block_id"]
        if bid not in block_ids_in_ep:
            invalid_id += 1
            errors.append(f"E{ep_num:02d}: invalid_id in hooks: {bid!r}")
            continue
        if bid in seen_hook_ids:
            continue
        seen_hook_ids.add(bid)
        valid_hooks.append(cleaned)
        if len(valid_hooks) >= 5:
            break

    seen_cliff_ids: set[str] = set()
    valid_cliffs: list[dict] = []
    for item in cliffs_raw:
        cleaned, reason = _validate_cliff(item)
        if cleaned is None:
            invalid_item += 1
            continue
        bid = cleaned["block_id"]
        if bid not in block_ids_in_ep:
            invalid_id += 1
            errors.append(f"E{ep_num:02d}: invalid_id in cliffhangers: {bid!r}")
            continue
        if bid in seen_cliff_ids:
            continue
        seen_cliff_ids.add(bid)
        valid_cliffs.append(cleaned)
        if len(valid_cliffs) >= 5:
            break

    return {
        "hooks": valid_hooks,
        "cliffhangers": valid_cliffs,
        "ending": ending_raw,
        "_invalid_item": invalid_item,
        "_invalid_id": invalid_id,
        "_total_ids_returned": len(all_ids),
    }, errors


# ---------------------------------------------------------------------------
# Per-episode processor
# ---------------------------------------------------------------------------

def _process_episode(ep_dict: dict) -> dict:
    """Run beats detection for one episode. Always returns a result dict."""
    ep_num = ep_dict["episode"]
    logline = ep_dict.get("logline", "")
    continuity = ep_dict.get("continuity_notes", "")

    scenes_dict = {sc["id"]: sc for sc in ep_dict.get("scenes", [])}
    script = format_blocks(ep_dict["blocks"], scenes_dict)

    try:
        raw = complete_json(
            "beats",
            {
                "episode": str(ep_num),
                "logline": logline,
                "continuity": continuity,
                "script": script,
            },
            tag=f"beats:E{ep_num:02d}",
        )
    except LLMQuotaExhausted:
        raise  # let run_beats propagate it to stop the whole run
    except LLMError as exc:
        return {
            "episode": ep_num,
            "hooks": [],
            "cliffhangers": [],
            "ending": {},
            "errors": [f"LLMError: {exc}"],
            "stats": {"invalid_item": 0, "invalid_id": 0, "total_ids_returned": 0},
        }

    block_ids_in_ep = {bl["id"] for bl in ep_dict["blocks"]}
    validated, errors = _validate_response(raw, ep_num, block_ids_in_ep)

    block_map = {bl["id"]: bl for bl in ep_dict["blocks"]}

    for hook in validated["hooks"]:
        bl = block_map[hook["block_id"]]
        hook["block_type"] = bl["type"]
        hook["start"] = bl["start"]
        hook["end"] = bl["end"]
        hook["clean_start"] = _find_clean_start(bl["start"], ep_dict["blocks"])

    for cliff in validated["cliffhangers"]:
        bl = block_map[cliff["block_id"]]
        cliff["block_type"] = bl["type"]
        cliff["start"] = bl["start"]
        cliff["end"] = bl["end"]

    return {
        "episode": ep_num,
        "hooks": validated["hooks"],
        "cliffhangers": validated["cliffhangers"],
        "ending": validated["ending"],
        "errors": errors,
        "stats": {
            "invalid_item": validated["_invalid_item"],
            "invalid_id": validated["_invalid_id"],
            "total_ids_returned": validated["_total_ids_returned"],
        },
    }


def run_beats(episodes: list[dict]) -> tuple[list[dict], list[int]]:
    """Process episodes in order.

    Returns (results, quota_remaining_ep_nums).
    quota_remaining_ep_nums is non-empty when the daily quota was hit mid-run;
    it lists episode numbers that were NOT attempted.
    """
    results: list[dict] = []
    for i, ep in enumerate(episodes):
        try:
            result = _process_episode(ep)
            results.append(result)
        except LLMQuotaExhausted:
            remaining = [e["episode"] for e in episodes[i:]]
            return results, remaining
    return results, []


# ---------------------------------------------------------------------------
# Token log reader
# ---------------------------------------------------------------------------

def _read_token_stats(since_iso: str) -> dict:
    """Read usage log rows since since_iso; return summary dict."""
    if not _LOG_PATH.exists():
        return {"calls": 0, "cached": 0, "uncached": 0,
                "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    rows = []
    with _LOG_PATH.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("time", "") >= since_iso:
                rows.append(row)
    cached = sum(1 for r in rows if r.get("cached") == "true")
    return {
        "calls": len(rows),
        "cached": cached,
        "uncached": len(rows) - cached,
        "prompt_tokens": sum(int(r.get("prompt_tokens", 0)) for r in rows),
        "completion_tokens": sum(int(r.get("completion_tokens", 0)) for r in rows),
        "total_tokens": sum(int(r.get("total_tokens", 0)) for r in rows),
    }


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def _build_report(
    results: list[dict],
    evals_checks: list[dict],
    token_stats: dict,
    show_title: str,
) -> str:
    lines: list[str] = [f"# Beats Report — {show_title}\n"]

    # --- 1. Totals ---
    llm_failed = [r for r in results if any("LLMError" in e for e in r.get("errors", []))]
    done = len(results) - len(llm_failed)
    total_hooks = sum(len(r["hooks"]) for r in results)
    total_cliffs = sum(len(r["cliffhangers"]) for r in results)
    total_invalid_id = sum(r["stats"]["invalid_id"] for r in results)
    total_invalid_item = sum(r["stats"]["invalid_item"] for r in results)
    total_ids_returned = sum(r["stats"]["total_ids_returned"] for r in results)
    made_up_rate = total_invalid_id / total_ids_returned if total_ids_returned else 0.0

    lines.append("## 1. Totals\n")
    lines.append(f"| Metric | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| Episodes done | {done} |")
    lines.append(f"| Episodes failed (LLMError) | {len(llm_failed)} |")
    lines.append(f"| Hooks kept | {total_hooks} |")
    lines.append(f"| Cliffhangers kept | {total_cliffs} |")
    lines.append(f"| invalid_id | {total_invalid_id} |")
    lines.append(f"| invalid_item | {total_invalid_item} |")
    lines.append(
        f"| Made-up ID rate | {made_up_rate:.1%} "
        f"({total_invalid_id}/{total_ids_returned}) |"
    )
    if llm_failed:
        failed_ep_str = ", ".join(f"E{r['episode']:02d}" for r in llm_failed)
        lines.append(f"\nFailed episodes: {failed_ep_str}")
    lines.append("")

    # --- 2. Distributions ---
    lines.append("## 2. Distributions\n")

    hook_type_counts: dict[str, int] = {}
    sp_counts: dict[int, int] = {}
    tension_counts: dict[int, int] = {}
    for r in results:
        for h in r["hooks"]:
            t = h.get("type", "unknown")
            hook_type_counts[t] = hook_type_counts.get(t, 0) + 1
            sp = h.get("stop_power", 0)
            sp_counts[sp] = sp_counts.get(sp, 0) + 1
        for c in r["cliffhangers"]:
            ten = c.get("tension", 0)
            tension_counts[ten] = tension_counts.get(ten, 0) + 1

    lines.append("**Hook types:**")
    for ht, cnt in sorted(hook_type_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- {ht}: {cnt}")

    lines.append("\n**Stop power distribution (hooks):**")
    for sp in range(5, 0, -1):
        lines.append(f"- {sp}: {sp_counts.get(sp, 0)}")

    lines.append("\n**Tension distribution (cliffhangers):**")
    for ten in range(5, 0, -1):
        lines.append(f"- {ten}: {tension_counts.get(ten, 0)}")
    lines.append("")

    # --- 3. Per-episode table ---
    lines.append("## 3. Per-episode table\n")
    lines.append("| Episode | Hooks | Best stop_power | Cliffhangers | Best tension | ending_type |")
    lines.append("|---|---|---|---|---|---|")
    for r in results:
        ep = r["episode"]
        hooks = r["hooks"]
        cliffs = r["cliffhangers"]
        best_sp = max((h["stop_power"] for h in hooks), default=0)
        best_ten = max((c["tension"] for c in cliffs), default=0)
        ending_type = r.get("ending", {}).get("ending_type", "?")
        err_marker = " ⚠" if r["errors"] else ""
        lines.append(
            f"| E{ep:02d}{err_marker} | {len(hooks)} | {best_sp} "
            f"| {len(cliffs)} | {best_ten} | {ending_type} |"
        )
    lines.append("")

    # --- 4. Hooks with clean_start: null ---
    null_starts = [
        (r["episode"], h["block_id"])
        for r in results
        for h in r["hooks"]
        if h.get("clean_start") is None
    ]
    lines.append("## 4. Hooks with clean_start: null\n")
    lines.append(f"Count: {len(null_starts)}")
    if null_starts:
        lines.append("IDs: " + ", ".join(f"E{ep:02d}/{bid}" for ep, bid in null_starts))
    lines.append("")

    # --- 5. Cliffhanger block types ---
    cliff_type_counts: dict[str, int] = {}
    for r in results:
        for c in r["cliffhangers"]:
            bt = c.get("block_type", "UNKNOWN")
            cliff_type_counts[bt] = cliff_type_counts.get(bt, 0) + 1

    lines.append("## 5. Cliffhanger block types\n")
    for bt, cnt in sorted(cliff_type_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- {bt}: {cnt}")
    lines.append("")

    # --- 6. Token usage ---
    lines.append("## 6. Token usage this run\n")
    lines.append(f"| Metric | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| Calls | {token_stats['calls']} |")
    lines.append(f"| Cached | {token_stats['cached']} |")
    lines.append(f"| Uncached | {token_stats['uncached']} |")
    lines.append(f"| Prompt tokens | {token_stats['prompt_tokens']} |")
    lines.append(f"| Completion tokens | {token_stats['completion_tokens']} |")
    lines.append(f"| Total tokens | {token_stats['total_tokens']} |")
    lines.append("")

    # --- 7. Eval results ---
    lines.append("## 7. Eval results\n")
    if not evals_checks:
        lines.append("(no eval file found — skipped)")
    else:
        for chk in evals_checks:
            status = chk["status"]
            check = chk["check"]
            actual = chk.get("actual", "")
            expected = chk.get("expected", "")
            lines.append(f"- **{status}** {check}: expected `{expected}`, got `{actual}`")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mark hook and cliffhanger beats per episode."
    )
    parser.add_argument("show_dir", type=Path, help="Path to show folder")
    parser.add_argument(
        "--episodes",
        default="",
        help="Comma-separated episode numbers (default: all)",
    )
    args = parser.parse_args()

    show_dir: Path = args.show_dir.resolve()
    if not show_dir.is_dir():
        sys.exit(f"Error: {show_dir} is not a directory")

    show = load_show(show_dir)

    # Select episodes
    if args.episodes.strip():
        selected_nums = {int(x.strip()) for x in args.episodes.split(",")}
        episodes = [ep for ep in show.episodes if ep["episode"] in selected_nums]
        missing = selected_nums - {ep["episode"] for ep in episodes}
        if missing:
            print(f"Warning: episodes not found: {sorted(missing)}", file=sys.stderr)
    else:
        episodes = list(show.episodes)

    episodes.sort(key=lambda ep: ep["episode"])
    print(f"Processing {len(episodes)} episode(s)…")

    run_start_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    results, quota_remaining = run_beats(episodes)

    # Save beats.json
    out_dir = _REPO_ROOT / "outputs" / show.slug / "beats"
    out_dir.mkdir(parents=True, exist_ok=True)
    beats_json = {
        "show": show.title,
        "slug": show.slug,
        "episodes": results,
    }
    (out_dir / "beats.json").write_text(
        json.dumps(beats_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Saved: {out_dir / 'beats.json'}")

    # Run evals
    from .eval_beats import run_evals
    evals_path = _REPO_ROOT / "evals" / f"{show.slug}.json"
    evals_checks = run_evals(results, show, evals_path)

    # Token stats
    token_stats = _read_token_stats(run_start_iso)

    # Build report
    report = _build_report(results, evals_checks, token_stats, show.title)
    (out_dir / "beats_report.md").write_text(report, encoding="utf-8")
    print(f"Saved: {out_dir / 'beats_report.md'}\n")

    # Short stdout summary
    llm_failed = sum(1 for r in results if any("LLMError" in e for e in r.get("errors", [])))
    total_hooks = sum(len(r["hooks"]) for r in results)
    total_cliffs = sum(len(r["cliffhangers"]) for r in results)
    total_invalid_id = sum(r["stats"]["invalid_id"] for r in results)
    total_ids_returned = sum(r["stats"]["total_ids_returned"] for r in results)
    made_up_rate = total_invalid_id / total_ids_returned if total_ids_returned else 0.0
    print(
        f"Done: {len(results) - llm_failed} ok, {llm_failed} failed  "
        f"hooks={total_hooks}  cliffs={total_cliffs}  "
        f"made-up IDs={total_invalid_id}/{total_ids_returned} ({made_up_rate:.1%})"
    )
    print(
        f"Tokens this run: {token_stats['total_tokens']} total "
        f"({token_stats['cached']} cached calls, {token_stats['uncached']} uncached)"
    )

    if quota_remaining:
        remaining_str = ", ".join(f"E{n:02d}" for n in quota_remaining)
        print(f"\nDAILY QUOTA EXHAUSTED — stopped early.")
        print(f"Not attempted ({len(quota_remaining)}): {remaining_str}")
        print("Swap the API key in .env and re-run.")

    if evals_checks:
        print("\nEval results:")
        for chk in evals_checks:
            print(f"  {chk['status']:4s}  {chk['check']}  ({chk.get('actual', '')})")


if __name__ == "__main__":
    main()

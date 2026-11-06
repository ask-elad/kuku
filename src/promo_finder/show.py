"""Shared show loader.

CLI: python -m promo_finder.show "<show folder>"  (prints summary)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


class Show:
    def __init__(self, title: str, slug: str, episodes: list[dict]) -> None:
        self.title = title
        self.slug = slug
        self.episodes = episodes
        self._block_index: dict[str, dict] = {}
        self._episode_index: dict[int, dict] = {}
        for ep in episodes:
            self._episode_index[ep["episode"]] = ep
            for bl in ep["blocks"]:
                self._block_index[bl["id"]] = bl

    def block(self, block_id: str) -> dict | None:
        return self._block_index.get(block_id)

    def blocks_in(self, episode: int, t0: float, t1: float) -> list[dict]:
        ep = self._episode_index.get(episode)
        if ep is None:
            return []
        return [b for b in ep["blocks"] if b["start"] < t1 and b["end"] > t0]

    def episode_duration(self, episode: int) -> float:
        ep = self._episode_index.get(episode)
        return ep["duration"] if ep else 0.0


def load_show(show_dir: str | Path) -> Show:
    from .parse import make_slug

    show_dir = Path(show_dir).resolve()
    slug = make_slug(show_dir.name)
    episodes_path = Path.cwd() / "build" / slug / "episodes.json"

    if not episodes_path.exists():
        result = subprocess.run(
            [sys.executable, "-m", "promo_finder.parse", str(show_dir)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Parser failed:\n{result.stderr}")
        if not episodes_path.exists():
            raise RuntimeError(f"Parser ran but {episodes_path} not found")

    data = json.loads(episodes_path.read_text(encoding="utf-8"))
    return Show(
        title=data["show"]["title"],
        slug=data["show"]["slug"],
        episodes=data["episodes"],
    )

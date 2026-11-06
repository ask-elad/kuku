"""Time helpers shared across the promo-finder pipeline."""
from __future__ import annotations


def parse_time(s: str) -> float:
    """Parse 'MM:SS.ss' to float seconds."""
    s = s.strip()
    mm, ss = s.split(":", 1)
    return int(mm) * 60.0 + float(ss)


def fmt_time(t: float) -> str:
    """Format float seconds as 'MM:SS.ss'."""
    centis = round(t * 100)
    total_secs, cs = divmod(centis, 100)
    mins, secs = divmod(total_secs, 60)
    return f"{mins:02d}:{secs:02d}.{cs:02d}"

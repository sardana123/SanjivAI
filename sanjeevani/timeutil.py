"""Minute-resolution local time helpers. All stored times are naive local ISO strings."""
from __future__ import annotations

from datetime import date, datetime, timedelta

FMT = "%Y-%m-%dT%H:%M"


def fmt(dt: datetime) -> str:
    return dt.strftime(FMT)


def parse(s: str) -> datetime:
    return datetime.strptime(s, FMT)


def now_local() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


def day_bounds(d: date) -> tuple[str, str]:
    start = datetime(d.year, d.month, d.day)
    return fmt(start), fmt(start + timedelta(days=1))


def spoken_time(dt: datetime, lang: str = "en") -> str:
    """Human/TTS friendly clock time."""
    h12 = dt.hour % 12 or 12
    mm = f"{dt.minute:02d}"
    if lang == "hi":
        h = dt.hour
        part = "सुबह" if 5 <= h < 12 else "दोपहर" if 12 <= h < 17 else "शाम" if 17 <= h < 21 else "रात"
        return f"{part} {h12}:{mm} बजे"
    return f"{h12}:{mm} {'AM' if dt.hour < 12 else 'PM'}"

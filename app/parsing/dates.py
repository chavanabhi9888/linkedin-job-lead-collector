"""Post-date resolution and the time-window filter."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from app.domain import TimeFilter
from app.utils.urls import extract_post_ref

UTC = timezone.utc
_REL_RE = re.compile(
    r"(?<![\w])(\d{1,3})\s*"
    r"(seconds?|minutes?|hours?|days?|weeks?|months?|years?|mo|min|yr|hr|wk|s|m|h|d|w|y)\b",
    re.I,
)
_MIN_PLAUSIBLE = datetime(2012, 1, 1, tzinfo=UTC)
# Windows are applied with a small grace because relative labels ("1d") are coarse.
_GRACE = timedelta(hours=1)


def parse_relative_label(label: str | None, now: datetime) -> datetime | None:
    """'2h' / '1d' / '3w' / '1mo' / '5 minutes ago' -> approximate datetime."""
    m = _REL_RE.search(label or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit.startswith("mo"):
        delta = timedelta(days=30 * n)
    elif unit.startswith("mi") or unit == "m":
        delta = timedelta(minutes=n)
    elif unit.startswith("s"):
        delta = timedelta(seconds=n)
    elif unit.startswith("h"):
        delta = timedelta(hours=n)
    elif unit.startswith("d"):
        delta = timedelta(days=n)
    elif unit.startswith("w"):
        delta = timedelta(weeks=n)
    else:
        delta = timedelta(days=365 * n)
    return now - delta


def datetime_from_post_id(post_id: int, now: datetime) -> datetime | None:
    """LinkedIn post ids embed a millisecond timestamp in their high bits (id >> 22)."""
    try:
        ts = datetime.fromtimestamp((post_id >> 22) / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return ts if _MIN_PLAUSIBLE <= ts <= now + timedelta(days=1) else None


def resolve_post_date(
    post_url: str, posted_at: datetime | None, posted_label: str | None, now: datetime
) -> datetime | None:
    """Best available date: explicit timestamp > id embedded in URL > relative label."""
    if posted_at is not None:
        return posted_at if posted_at.tzinfo else posted_at.replace(tzinfo=UTC)
    ref = extract_post_ref(post_url)
    if ref:
        from_id = datetime_from_post_id(ref[1], now)
        if from_id:
            return from_id
    return parse_relative_label(posted_label, now)


def is_within_window(
    post_date: datetime | None, time_filter: TimeFilter, now: datetime, *, allow_unknown: bool = True
) -> bool:
    if post_date is None:
        return allow_unknown
    age = now - post_date
    return timedelta(minutes=-10) <= age <= time_filter.window + _GRACE

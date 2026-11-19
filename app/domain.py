"""Source-agnostic domain types shared by every layer."""
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import timedelta


class TimeFilter(str, enum.Enum):
    PAST_24H = "past_24h"
    PAST_WEEK = "past_week"

    @property
    def window(self) -> timedelta:
        return timedelta(hours=24) if self is TimeFilter.PAST_24H else timedelta(days=7)


@dataclass(frozen=True)
class SearchCriteria:
    keyword: str
    location: str
    time_filter: TimeFilter
    max_posts: int = 50

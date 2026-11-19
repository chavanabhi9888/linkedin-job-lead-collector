"""The seam between the LinkedIn-specific layer and the business logic.

Anything that can yield ``RawPost`` objects for a ``SearchCriteria`` is a valid
source (browser, official API, licensed data feed, file import...). Nothing
outside ``app/sources`` knows how posts are obtained.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, Protocol

from app.domain import SearchCriteria


@dataclass(frozen=True)
class RawPost:
    post_url: str
    text: str
    author_name: str | None = None
    profile_url: str | None = None
    posted_at: datetime | None = None   # exact timestamp, if the source has one
    posted_label: str | None = None     # relative label such as "2h" / "1w"


class LeadSource(Protocol):
    name: str

    def fetch_posts(self, criteria: SearchCriteria) -> Iterator[RawPost]:
        """Yield posts lazily. Raise ``SourceError`` subclasses on failure."""
        ...

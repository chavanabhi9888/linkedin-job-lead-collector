"""File-backed source: proves the source layer is swappable, and powers demos/tests."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from app.domain import SearchCriteria
from app.sources.base import RawPost
from app.sources.errors import SourceConfigurationError


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class JsonFileSource:
    name = "json_file"

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def fetch_posts(self, criteria: SearchCriteria) -> Iterator[RawPost]:
        try:
            items = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(items, list):
                raise ValueError("top-level JSON value must be a list")
        except (OSError, ValueError) as exc:
            raise SourceConfigurationError(f"Cannot read JSON source {self._path}: {exc}") from exc
        for item in items[: criteria.max_posts]:
            yield RawPost(
                post_url=item["post_url"],
                text=item.get("text", ""),
                author_name=item.get("author_name"),
                profile_url=item.get("profile_url"),
                posted_at=_parse_dt(item.get("posted_at")),
                posted_label=item.get("posted_label"),
            )

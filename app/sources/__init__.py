"""Source factory. Add new sources here; nothing else in the codebase changes."""
from __future__ import annotations

from app.config import Settings
from app.sources.base import LeadSource, RawPost
from app.sources.errors import SourceConfigurationError

__all__ = ["LeadSource", "RawPost", "build_source"]


def build_source(settings: Settings) -> LeadSource:
    kind = settings.lead_source.lower()
    if kind == "linkedin":
        from app.sources.linkedin import (
            LinkedInSource,  # lazy: Playwright only when needed
        )

        return LinkedInSource(settings)
    if kind == "json_file":
        from app.sources.json_file import JsonFileSource

        if not settings.json_source_path:
            raise SourceConfigurationError("JSON_SOURCE_PATH must be set for LEAD_SOURCE=json_file")
        return JsonFileSource(settings.json_source_path)
    raise SourceConfigurationError(f"Unknown LEAD_SOURCE {settings.lead_source!r}")

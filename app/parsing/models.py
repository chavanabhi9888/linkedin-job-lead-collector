from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LeadCreate(BaseModel):
    """A validated lead, ready to persist."""

    author_name: str | None = Field(default=None, max_length=255)
    profile_url: str | None = Field(default=None, max_length=1024)
    company: str | None = Field(default=None, max_length=255)
    job_title: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    post_url: str = Field(max_length=1024)
    post_date: datetime | None = None
    email: str | None = Field(default=None, max_length=512)   # multiple joined with "; "
    phone: str | None = Field(default=None, max_length=255)   # multiple joined with "; "
    post_text: str | None = None

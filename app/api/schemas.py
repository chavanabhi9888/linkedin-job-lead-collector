from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import JobStatus
from app.domain import TimeFilter


class RunJobRequest(BaseModel):
    keyword: str | None = Field(default=None, min_length=2, max_length=100, examples=["Python Developer"])
    location: str | None = Field(default=None, min_length=2, max_length=100, examples=["Pune, India"])
    time_filter: TimeFilter | None = Field(default=None, examples=["past_24h"])
    max_posts: int | None = Field(default=None, ge=1, le=200)

    @field_validator("keyword", "location")
    @classmethod
    def _no_control_chars(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v or any(ord(c) < 32 for c in v):
            raise ValueError("must be non-empty printable text")
        return v


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    job_id: uuid.UUID = Field(validation_alias="id")
    status: JobStatus
    keyword: str
    location: str
    time_filter: str
    max_posts: int
    posts_seen: int
    new_leads: int
    duplicate_posts: int
    skipped_posts: int
    emails_found: int
    phones_found: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    author_name: str | None
    profile_url: str | None
    company: str | None
    job_title: str | None
    location: str | None
    post_url: str
    post_date: datetime | None
    email: str | None
    phone: str | None
    post_text: str | None
    collected_at: datetime


class LeadListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[LeadResponse]


class HealthResponse(BaseModel):
    status: str
    database: str

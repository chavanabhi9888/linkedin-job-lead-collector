from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NEEDS_MANUAL_ACTION = "NEEDS_MANUAL_ACTION"  # CAPTCHA / MFA / checkpoint


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=32), nullable=False, default=JobStatus.QUEUED, index=True
    )
    keyword: Mapped[str] = mapped_column(String(100), nullable=False)
    location: Mapped[str] = mapped_column(String(100), nullable=False)
    time_filter: Mapped[str] = mapped_column(String(20), nullable=False)
    max_posts: Mapped[int] = mapped_column(Integer, nullable=False)

    posts_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_leads: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_posts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_posts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    emails_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    phones_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    screenshot_path: Mapped[str | None] = mapped_column(String(512))  # internal only, not exposed by the API

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_post_date", "post_date"),
        Index("ix_leads_collected_at", "collected_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    author_name: Mapped[str | None] = mapped_column(String(255))
    profile_url: Mapped[str | None] = mapped_column(String(1024))
    company: Mapped[str | None] = mapped_column(String(255))
    job_title: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    post_url: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)  # dedup key
    post_date: Mapped[datetime | None] = mapped_column(UTCDateTime)
    email: Mapped[str | None] = mapped_column(String(512))
    phone: Mapped[str | None] = mapped_column(String(255))
    post_text: Mapped[str | None] = mapped_column(Text)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("jobs.id", ondelete="SET NULL"))

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session

from app.db.models import Job, JobStatus, Lead, utcnow
from app.domain import SearchCriteria
from app.parsing.models import LeadCreate


@dataclass(frozen=True)
class LeadFilter:
    has_email: bool | None = None
    has_phone: bool | None = None
    company: str | None = None
    q: str | None = None
    since: datetime | None = None   # post_date >= since
    job_id: uuid.UUID | None = None


@dataclass(frozen=True)
class InsertResult:
    inserted: list[LeadCreate]
    duplicates: int


def _insert_for(session: Session):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:  # pragma: no cover
        raise NotImplementedError(f"unsupported dialect {dialect}")
    return insert


class LeadRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_new(self, leads: Sequence[LeadCreate], job_id: uuid.UUID | None = None) -> InsertResult:
        """Insert leads, skipping any whose post_url already exists.

        ``INSERT ... ON CONFLICT DO NOTHING`` keeps this atomic and race-safe
        even if two processes collect the same post.
        """
        insert = _insert_for(self.session)
        inserted: list[LeadCreate] = []
        duplicates = 0
        seen: set[str] = set()
        for lead in leads:
            if lead.post_url in seen:
                duplicates += 1
                continue
            seen.add(lead.post_url)
            values = lead.model_dump()
            values.update(job_id=job_id, collected_at=utcnow())
            stmt = (
                insert(Lead).values(**values).on_conflict_do_nothing(index_elements=["post_url"]).returning(Lead.id)
            )
            if self.session.execute(stmt).scalar_one_or_none() is None:
                duplicates += 1
            else:
                inserted.append(lead)
        return InsertResult(inserted=inserted, duplicates=duplicates)

    @staticmethod
    def _apply(stmt: Select, f: LeadFilter) -> Select:
        if f.has_email is True:
            stmt = stmt.where(Lead.email.is_not(None))
        elif f.has_email is False:
            stmt = stmt.where(Lead.email.is_(None))
        if f.has_phone is True:
            stmt = stmt.where(Lead.phone.is_not(None))
        elif f.has_phone is False:
            stmt = stmt.where(Lead.phone.is_(None))
        if f.company:
            stmt = stmt.where(func.lower(Lead.company).contains(f.company.lower(), autoescape=True))
        if f.q:
            needle = f.q.lower()
            stmt = stmt.where(
                func.lower(func.coalesce(Lead.post_text, "")).contains(needle, autoescape=True)
                | func.lower(func.coalesce(Lead.job_title, "")).contains(needle, autoescape=True)
                | func.lower(func.coalesce(Lead.author_name, "")).contains(needle, autoescape=True)
            )
        if f.since:
            stmt = stmt.where(Lead.post_date >= f.since)
        if f.job_id:
            stmt = stmt.where(Lead.job_id == f.job_id)
        return stmt

    def list(self, f: LeadFilter, *, limit: int = 50, offset: int = 0) -> tuple[int, list[Lead]]:
        total = self.session.scalar(self._apply(select(func.count(Lead.id)), f)) or 0
        stmt = self._apply(select(Lead), f).order_by(Lead.post_date.desc().nulls_last(), Lead.id.desc())
        return total, list(self.session.scalars(stmt.limit(limit).offset(offset)))

    def all(self, f: LeadFilter, *, limit: int = 10_000) -> list[Lead]:
        stmt = self._apply(select(Lead), f).order_by(Lead.post_date.desc().nulls_last(), Lead.id.desc())
        return list(self.session.scalars(stmt.limit(limit)))


class JobRepository:
    ACTIVE = (JobStatus.QUEUED, JobStatus.RUNNING)

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, criteria: SearchCriteria) -> Job:
        job = Job(
            keyword=criteria.keyword,
            location=criteria.location,
            time_filter=criteria.time_filter.value,
            max_posts=criteria.max_posts,
            status=JobStatus.QUEUED,
        )
        self.session.add(job)
        self.session.flush()
        return job

    def get(self, job_id: uuid.UUID) -> Job | None:
        return self.session.get(Job, job_id)

    def active_job(self) -> Job | None:
        return self.session.scalars(select(Job).where(Job.status.in_(self.ACTIVE)).limit(1)).first()

    def mark_running(self, job_id: uuid.UUID) -> None:
        self.session.execute(
            update(Job).where(Job.id == job_id).values(status=JobStatus.RUNNING, started_at=utcnow())
        )

    def add_progress(
        self, job_id: uuid.UUID, *, posts_seen=0, new_leads=0, duplicates=0, skipped=0, emails=0, phones=0
    ) -> None:
        self.session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                posts_seen=Job.posts_seen + posts_seen,
                new_leads=Job.new_leads + new_leads,
                duplicate_posts=Job.duplicate_posts + duplicates,
                skipped_posts=Job.skipped_posts + skipped,
                emails_found=Job.emails_found + emails,
                phones_found=Job.phones_found + phones,
            )
        )

    def finish(
        self,
        job_id: uuid.UUID,
        status: JobStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        screenshot_path: str | None = None,
    ) -> None:
        self.session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status=status,
                finished_at=utcnow(),
                error_code=error_code,
                error_message=(error_message or None) and error_message[:2000],
                screenshot_path=screenshot_path,
            )
        )

    def fail_stale(self) -> int:
        """Mark jobs left QUEUED/RUNNING by a previous process as failed."""
        result = self.session.execute(
            update(Job)
            .where(Job.status.in_(self.ACTIVE))
            .values(
                status=JobStatus.FAILED,
                finished_at=utcnow(),
                error_code="interrupted",
                error_message="Process stopped before the job finished.",
            )
        )
        return result.rowcount or 0

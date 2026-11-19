"""Business logic: pull posts from any LeadSource, parse, dedupe, persist.

Knows nothing about LinkedIn or browsers; it only talks to the ``LeadSource`` protocol.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import JobStatus
from app.db.repositories import JobRepository, LeadRepository
from app.db.session import session_scope
from app.domain import SearchCriteria, TimeFilter
from app.logging_config import job_id_var
from app.parsing.models import LeadCreate
from app.parsing.post_parser import parse_post
from app.sources.base import LeadSource
from app.sources.errors import ChallengeRequiredError, SourceError

logger = logging.getLogger(__name__)
BATCH_SIZE = 20


@dataclass
class _Counters:
    seen: int = 0
    skipped: int = 0
    duplicates: int = 0
    new: int = 0
    emails: int = 0
    phones: int = 0
    no_contact: int = 0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CollectorService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        source_factory: Callable[[], LeadSource],
        *,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._sf, self._source_factory, self._clock = session_factory, source_factory, clock

    def run(self, job_id: uuid.UUID) -> JobStatus:
        token = job_id_var.set(str(job_id))
        try:
            return self._run(job_id)
        finally:
            job_id_var.reset(token)

    # ------------------------------------------------------------------
    def _run(self, job_id: uuid.UUID) -> JobStatus:
        with session_scope(self._sf) as s:
            repo = JobRepository(s)
            job = repo.get(job_id)
            if job is None:
                raise LookupError(f"job {job_id} not found")
            criteria = SearchCriteria(job.keyword, job.location, TimeFilter(job.time_filter), job.max_posts)
            repo.mark_running(job_id)
        logger.info("job_started", extra={"max_posts": criteria.max_posts, "time_filter": criteria.time_filter.value})

        seen_urls: set[str] = set()
        batch: list[LeadCreate] = []
        totals = _Counters()
        pending = _Counters()  # not yet written to the job row
        status, error_code, error_message, screenshot = JobStatus.SUCCEEDED, None, None, None

        iterator = None
        try:
            iterator = iter(self._source_factory().fetch_posts(criteria))
            for raw in iterator:
                pending.seen += 1
                lead = parse_post(raw, criteria, self._clock())
                if lead is None:
                    pending.skipped += 1
                    continue
                if lead.post_url in seen_urls:
                    pending.duplicates += 1
                    continue
                seen_urls.add(lead.post_url)
                if not lead.email and not lead.phone:
                    totals.no_contact += 1  # kept: still a useful lead (author/profile/post link)
                batch.append(lead)
                if len(batch) >= BATCH_SIZE:
                    self._flush(job_id, batch, pending, totals)
                    batch = []
        except SourceError as exc:
            status = JobStatus.NEEDS_MANUAL_ACTION if isinstance(exc, ChallengeRequiredError) else JobStatus.FAILED
            error_code, error_message, screenshot = exc.code, str(exc), exc.screenshot_path
            logger.error("job_source_error", extra={"error_code": exc.code, "retryable": exc.retryable})
        except Exception as exc:  # noqa: BLE001 - last line of defence for the worker thread
            status, error_code, error_message = JobStatus.FAILED, "unexpected_error", f"{type(exc).__name__}: {exc}"
            logger.exception("job_unexpected_error")
        finally:
            close = getattr(iterator, "close", None)
            if close:
                try:
                    close()
                except Exception:  # noqa: BLE001
                    logger.debug("source_close_error", exc_info=True)
            try:
                self._flush(job_id, batch, pending, totals)  # keep partial results even on failure
            except Exception as exc:  # noqa: BLE001
                status, error_code, error_message = JobStatus.FAILED, "persist_error", f"{type(exc).__name__}: {exc}"
                logger.exception("job_flush_error")

        with session_scope(self._sf) as s:
            JobRepository(s).finish(
                job_id, status, error_code=error_code, error_message=error_message, screenshot_path=screenshot
            )
        logger.info("job_finished", extra={"status": status.value, **asdict(totals)})
        return status

    def _flush(self, job_id: uuid.UUID, batch: list[LeadCreate], pending: "_Counters", totals: "_Counters") -> None:
        with session_scope(self._sf) as s:
            result = LeadRepository(s).add_new(batch, job_id) if batch else None
            inserted = result.inserted if result else []
            emails = sum(1 for lead in inserted if lead.email)
            phones = sum(1 for lead in inserted if lead.phone)
            duplicates = pending.duplicates + (result.duplicates if result else 0)
            JobRepository(s).add_progress(
                job_id,
                posts_seen=pending.seen,
                new_leads=len(inserted),
                duplicates=duplicates,
                skipped=pending.skipped,
                emails=emails,
                phones=phones,
            )
        totals.seen += pending.seen
        totals.skipped += pending.skipped
        totals.duplicates += duplicates
        totals.new += len(inserted)
        totals.emails += emails
        totals.phones += phones
        pending.seen = pending.skipped = pending.duplicates = 0

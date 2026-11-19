"""Serialises collection jobs: at most one browser job at a time."""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Job
from app.db.repositories import JobRepository
from app.db.session import session_scope
from app.domain import SearchCriteria
from app.services.collector import CollectorService

logger = logging.getLogger(__name__)


class JobAlreadyRunningError(RuntimeError):
    pass


class Executor(Protocol):
    def submit(self, fn, *args): ...
    def shutdown(self, wait: bool = ..., **kwargs): ...


class JobRunner:
    def __init__(
        self, service: CollectorService, session_factory: sessionmaker[Session], executor: Executor | None = None
    ) -> None:
        self._service, self._sf = service, session_factory
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="collector")
        self._lock = threading.Lock()

    def submit(self, criteria: SearchCriteria) -> Job:
        with self._lock:
            with session_scope(self._sf) as s:
                repo = JobRepository(s)
                active = repo.active_job()
                if active:
                    raise JobAlreadyRunningError(f"Job {active.id} is still {active.status.value}")
                job = repo.create(criteria)
            self._executor.submit(self._safe_run, job.id)
        return job

    def _safe_run(self, job_id) -> None:
        try:
            self._service.run(job_id)
        except Exception:  # noqa: BLE001
            logger.exception("job_runner_crash", extra={"job": str(job_id)})

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

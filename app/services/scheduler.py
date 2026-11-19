"""APScheduler wiring. Runs inside the API process, so run a single API worker."""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings
from app.domain import SearchCriteria
from app.services.job_runner import JobAlreadyRunningError, JobRunner

logger = logging.getLogger(__name__)


def build_scheduler(settings: Settings, runner: JobRunner) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=settings.scheduler_timezone)

    def _tick() -> None:
        criteria = SearchCriteria(
            settings.default_keyword, settings.default_location, settings.default_time_filter, settings.default_max_posts
        )
        try:
            job = runner.submit(criteria)
            logger.info("scheduled_job_submitted", extra={"scheduled_job_id": str(job.id)})
        except JobAlreadyRunningError:
            logger.warning("scheduled_job_skipped_already_running")

    scheduler.add_job(
        _tick,
        CronTrigger.from_crontab(settings.scheduler_cron, timezone=settings.scheduler_timezone),
        id="scheduled_collect",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )
    return scheduler

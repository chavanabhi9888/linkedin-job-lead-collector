"""Run every keyword x location from a plan file, then export the results to Excel.

    python -m app.batch                       # uses search_plan.json
    python -m app.batch --plan my_plan.json
    python -m app.batch --dry-run             # show what would run, touch nothing
    python -m app.batch --no-export           # scrape only
    python -m app.batch --export-only         # skip scraping, export everything stored

Safety behaviour (same philosophy as the rest of the tool):
  * runs are sequential, with a randomised cool-down (>= 30 s) between searches;
  * the whole batch stops on CAPTCHA/MFA, login failure or rate limiting;
  * the batch also stops after N consecutive failed runs (default 3);
  * Ctrl+C stops cleanly, and whatever was collected is still exported.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db.models import Job, JobStatus, Lead
from app.db.repositories import JobRepository
from app.db.session import (
    create_db_engine,
    create_session_factory,
    init_db,
    session_scope,
)
from app.domain import SearchCriteria, TimeFilter
from app.exporters.excel import build_leads_workbook
from app.logging_config import configure_logging
from app.services.collector import CollectorService
from app.sources import LeadSource, build_source

logger = logging.getLogger(__name__)

MIN_COOLDOWN_S = 30
ABORT_CODES = {"login_failed", "challenge_required", "rate_limited", "configuration_error"}
_ALLOWED_KEYS = {
    "keywords", "locations", "time_filter", "max_posts", "cooldown_min_s", "cooldown_max_s",
    "stop_after_consecutive_failures", "skip_if_succeeded_within_hours",
    "export_scope", "export_require_contact", "export_dir",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ plan
@dataclass(frozen=True)
class Plan:
    keywords: list[str]
    locations: list[str]
    time_filter: TimeFilter
    max_posts: int
    cooldown_min_s: float
    cooldown_max_s: float
    stop_after_consecutive_failures: int
    skip_if_succeeded_within_hours: float
    export_scope: str             # "new" = leads from this batch, "all" = everything stored
    export_require_contact: bool  # only rows with an email or phone
    export_dir: Path

    def combos(self) -> list[tuple[str, str]]:
        """Location-major order, so your first location is finished first."""
        return [(k, loc) for loc in self.locations for k in self.keywords]


def _clean_list(raw, name: str) -> list[str]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"'{name}' must be a non-empty list")
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"'{name}' must contain only non-empty strings")
        value = " ".join(item.split())
        if value.lower() not in seen:
            seen.add(value.lower())
            out.append(value)
    return out


def load_plan(path: str | Path, settings: Settings) -> Plan:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))  # utf-8-sig: Notepad adds a BOM
    if not isinstance(data, dict):
        raise ValueError("plan file must contain a JSON object")
    unknown = set(data) - _ALLOWED_KEYS
    if unknown:
        raise ValueError(f"unknown plan keys: {', '.join(sorted(unknown))}")

    try:
        time_filter = TimeFilter(data.get("time_filter", settings.default_time_filter.value))
    except ValueError as exc:
        raise ValueError("'time_filter' must be 'past_24h' or 'past_week'") from exc
    max_posts = int(data.get("max_posts", settings.default_max_posts))
    cd_min = float(data.get("cooldown_min_s", 90))
    cd_max = float(data.get("cooldown_max_s", 180))
    scope = data.get("export_scope", "new")

    if not 1 <= max_posts <= 200:
        raise ValueError("'max_posts' must be between 1 and 200")
    if cd_min < MIN_COOLDOWN_S or cd_max < cd_min:
        raise ValueError(f"cooldowns must satisfy {MIN_COOLDOWN_S} <= cooldown_min_s <= cooldown_max_s")
    if scope not in ("new", "all"):
        raise ValueError("'export_scope' must be 'new' or 'all'")

    return Plan(
        keywords=_clean_list(data.get("keywords"), "keywords"),
        locations=_clean_list(data.get("locations"), "locations"),
        time_filter=time_filter,
        max_posts=max_posts,
        cooldown_min_s=cd_min,
        cooldown_max_s=cd_max,
        stop_after_consecutive_failures=max(1, int(data.get("stop_after_consecutive_failures", 3))),
        skip_if_succeeded_within_hours=float(data.get("skip_if_succeeded_within_hours", 0)),
        export_scope=scope,
        export_require_contact=bool(data.get("export_require_contact", False)),
        export_dir=Path(data.get("export_dir", "exports")),
    )


# ------------------------------------------------------------------ run
@dataclass
class Outcome:
    keyword: str
    location: str
    status: str
    new_leads: int = 0
    emails: int = 0
    phones: int = 0
    duplicates: int = 0
    error_code: str | None = None


@dataclass
class BatchResult:
    started_at: datetime
    outcomes: list[Outcome] = field(default_factory=list)
    job_ids: list[uuid.UUID] = field(default_factory=list)
    aborted_reason: str | None = None


def _recent_success(
    session: Session, keyword: str, location: str, tf: TimeFilter, hours: float, now: datetime
) -> uuid.UUID | None:
    if hours <= 0:
        return None
    stmt = (
        select(Job.id)
        .where(
            Job.status == JobStatus.SUCCEEDED,
            Job.time_filter == tf.value,
            Job.finished_at >= now - timedelta(hours=hours),
            func.lower(Job.keyword) == keyword.lower(),
            func.lower(Job.location) == location.lower(),
        )
        .order_by(Job.finished_at.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def run_batch(
    plan: Plan,
    session_factory: sessionmaker[Session],
    source_factory: Callable[[], LeadSource],
    *,
    sleep: Callable[[float], None] = time.sleep,
    uniform: Callable[[float, float], float] = random.uniform,
    clock: Callable[[], datetime] = _utcnow,
    out: Callable[[str], None] = print,
) -> BatchResult:
    combos = plan.combos()
    service = CollectorService(session_factory, source_factory, clock=clock)
    result = BatchResult(started_at=clock())
    consecutive_failures = 0
    current_job: uuid.UUID | None = None

    try:
        for i, (keyword, location) in enumerate(combos, start=1):
            label = f"[{i}/{len(combos)}] {keyword} @ {location}"

            with session_scope(session_factory) as s:
                prior = _recent_success(
                    s, keyword, location, plan.time_filter, plan.skip_if_succeeded_within_hours, clock()
                )
            if prior:
                result.job_ids.append(prior)  # keep its leads in a "new" export
                result.outcomes.append(Outcome(keyword, location, "SKIPPED"))
                out(f"{label} -> skipped (already succeeded within {plan.skip_if_succeeded_within_hours:g}h)")
                continue

            criteria = SearchCriteria(keyword, location, plan.time_filter, plan.max_posts)
            with session_scope(session_factory) as s:
                current_job = JobRepository(s).create(criteria).id
            result.job_ids.append(current_job)
            out(f"{label} -> running...")

            status = service.run(current_job)
            job_id, current_job = current_job, None
            with session_scope(session_factory) as s:
                job = JobRepository(s).get(job_id)
                outcome = Outcome(
                    keyword, location, status.value, job.new_leads, job.emails_found, job.phones_found,
                    job.duplicate_posts, job.error_code,
                )
            result.outcomes.append(outcome)
            out(
                f"{label} -> {outcome.status}: new={outcome.new_leads} emails={outcome.emails} "
                f"phones={outcome.phones} dups={outcome.duplicates}"
                + (f" error={outcome.error_code}" if outcome.error_code else "")
            )

            if status == JobStatus.NEEDS_MANUAL_ACTION or outcome.error_code in ABORT_CODES:
                result.aborted_reason = (
                    f"{outcome.error_code}: LinkedIn needs your attention. Run `python -m app.cli login`, "
                    "then re-run the batch (set skip_if_succeeded_within_hours to resume)."
                )
                break
            consecutive_failures = 0 if status == JobStatus.SUCCEEDED else consecutive_failures + 1
            if consecutive_failures >= plan.stop_after_consecutive_failures:
                result.aborted_reason = (
                    f"{consecutive_failures} consecutive failed runs (last error: {outcome.error_code})"
                )
                break

            if i < len(combos):
                delay = uniform(plan.cooldown_min_s, plan.cooldown_max_s)
                out(f"    cooling down {delay:.0f}s ...")
                sleep(delay)
    except KeyboardInterrupt:
        result.aborted_reason = "interrupted by user (Ctrl+C)"
        if current_job is not None:
            with session_scope(session_factory) as s:
                JobRepository(s).finish(
                    current_job, JobStatus.FAILED, error_code="interrupted", error_message="Stopped by user."
                )
    return result


# ------------------------------------------------------------------ export
def export_leads(
    session_factory: sessionmaker[Session],
    plan: Plan,
    job_ids: list[uuid.UUID],
    *,
    scope: str | None = None,
    clock: Callable[[], datetime] = _utcnow,
) -> tuple[Path, int]:
    scope = scope or plan.export_scope
    stmt = select(Lead)
    if scope == "new":
        stmt = stmt.where(Lead.job_id.in_(job_ids))
    if plan.export_require_contact:
        stmt = stmt.where(or_(Lead.email.is_not(None), Lead.phone.is_not(None)))
    stmt = stmt.order_by(Lead.post_date.desc().nulls_last(), Lead.id.desc())
    with session_scope(session_factory) as s:
        leads = list(s.scalars(stmt))

    plan.export_dir.mkdir(parents=True, exist_ok=True)
    path = plan.export_dir / f"leads_{clock().astimezone():%Y%m%d_%H%M%S}.xlsx"
    path.write_bytes(build_leads_workbook(leads))
    return path, len(leads)


def format_summary(result: BatchResult) -> str:
    lines = ["", f"{'Keyword @ Location':<44}{'Status':<22}{'New':>5}{'Mail':>6}{'Ph':>4}{'Dup':>5}"]
    for o in result.outcomes:
        name = f"{o.keyword} @ {o.location}"
        lines.append(f"{name:<44}{o.status:<22}{o.new_leads:>5}{o.emails:>6}{o.phones:>4}{o.duplicates:>5}")
    lines.append(
        f"TOTAL new leads={sum(o.new_leads for o in result.outcomes)} "
        f"emails={sum(o.emails for o in result.outcomes)} phones={sum(o.phones for o in result.outcomes)}"
    )
    if result.aborted_reason:
        lines.append(f"STOPPED EARLY: {result.aborted_reason}")
    return "\n".join(lines)


# ------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="app.batch", description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--plan", default="search_plan.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-export", action="store_true")
    parser.add_argument("--export-only", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, as_json=False)
    try:
        plan = load_plan(args.plan, settings)
    except (OSError, ValueError) as exc:
        print(f"Plan error: {exc}")
        return 1

    combos = plan.combos()
    avg_cooldown = (plan.cooldown_min_s + plan.cooldown_max_s) / 2
    est_min = len(combos) * (2 + avg_cooldown / 60)  # ~2 min per search was typical in practice
    print(
        f"{len(plan.keywords)} keywords x {len(plan.locations)} locations = {len(combos)} searches "
        f"(~{est_min / 60:.1f} h)"
    )

    if args.dry_run:
        for k, loc in combos:
            print(f"  {k} @ {loc}")
        return 0

    engine = create_db_engine(settings.database_url)
    init_db(engine)
    factory = create_session_factory(engine)

    result = BatchResult(started_at=_utcnow())
    if not args.export_only:
        result = run_batch(plan, factory, lambda: build_source(settings))
        print(format_summary(result))

    if args.no_export:
        return 2 if result.aborted_reason else 0
    path, rows = export_leads(factory, plan, result.job_ids, scope="all" if args.export_only else None)
    print(f"\nExcel export: {path.resolve()} ({rows} rows)")
    return 2 if result.aborted_reason else 0


if __name__ == "__main__":
    sys.exit(main())

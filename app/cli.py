"""Command line helpers.

  python -m app.cli login      # one-time interactive sign-in (you solve any CAPTCHA/MFA)
  python -m app.cli run        # run one collection synchronously
  python -m app.cli init-db    # create tables
"""
from __future__ import annotations

import argparse
import sys

from app.config import get_settings
from app.db.repositories import JobRepository
from app.db.session import (
    create_db_engine,
    create_session_factory,
    init_db,
    session_scope,
)
from app.domain import SearchCriteria, TimeFilter
from app.logging_config import configure_logging
from app.services.collector import CollectorService
from app.sources import build_source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="interactive LinkedIn sign-in; saves a session file")
    sub.add_parser("init-db", help="create database tables")
    run = sub.add_parser("run", help="run one collection synchronously")
    run.add_argument("--keyword")
    run.add_argument("--location")
    run.add_argument("--time-filter", choices=[t.value for t in TimeFilter])
    run.add_argument("--max-posts", type=int)
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, as_json=False)

    if args.cmd == "login":
        from app.sources.linkedin.auth import interactive_login

        ok = interactive_login(settings)
        print("Session saved." if ok else "Timed out waiting for login.")
        return 0 if ok else 1

    engine = create_db_engine(settings.database_url)
    init_db(engine)
    if args.cmd == "init-db":
        print("Tables created.")
        return 0

    factory = create_session_factory(engine)
    criteria = SearchCriteria(
        args.keyword or settings.default_keyword,
        args.location or settings.default_location,
        TimeFilter(args.time_filter) if args.time_filter else settings.default_time_filter,
        args.max_posts or settings.default_max_posts,
    )
    with session_scope(factory) as s:
        job = JobRepository(s).create(criteria)
    status = CollectorService(factory, lambda: build_source(settings)).run(job.id)
    with session_scope(factory) as s:
        job = JobRepository(s).get(job.id)
        print(f"{status.value}: job_id={job.id} new_leads={job.new_leads} emails={job.emails_found} phones={job.phones_found} "
      f"posts_seen={job.posts_seen} duplicates={job.duplicate_posts} skipped={job.skipped_posts} error={job.error_code}")
    return 0 if status.value == "SUCCEEDED" else 2


if __name__ == "__main__":
    sys.exit(main())

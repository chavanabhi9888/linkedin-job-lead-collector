from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import models  # noqa: F401
from app.db.base import Base
from app.domain import SearchCriteria, TimeFilter
from app.parsing.models import LeadCreate

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def post_id_for(dt: datetime) -> int:
    """Build a LinkedIn-style id whose embedded timestamp equals ``dt``."""
    return int(dt.timestamp() * 1000) << 22


def post_url_for(dt: datetime) -> str:
    return f"https://www.linkedin.com/feed/update/urn:li:activity:{post_id_for(dt)}/"


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    engine.dispose()


@pytest.fixture()
def criteria() -> SearchCriteria:
    return SearchCriteria("Python Developer", "Pune, India", TimeFilter.PAST_24H, 50)


def make_lead(n: int = 1, **overrides) -> LeadCreate:
    data = dict(
        author_name=f"Recruiter {n}",
        profile_url=f"https://www.linkedin.com/in/recruiter-{n}",
        company="Acme Tech",
        job_title="Python Developer",
        location="Pune",
        post_url=f"https://www.linkedin.com/feed/update/urn:li:activity:70000000000000000{n:02d}/",
        post_date=NOW - timedelta(hours=n),
        email=f"hr{n}@acme.io",
        phone=None,
        post_text="We are hiring a Python Developer",
    )
    data.update(overrides)
    return LeadCreate(**data)


@pytest.fixture()
def sample_json(tmp_path):
    recent = datetime.now(timezone.utc) - timedelta(hours=2)  # API tests use the real clock
    items = [
        {
            "post_url": post_url_for(recent),
            "author_name": "Asha Rao",
            "profile_url": "https://www.linkedin.com/in/asha-rao?trk=abc",
            "text": "Hiring at Acme Tech!\nRole: Python Developer\nLocation: Pune\nSend CV to jobs@acme.io or call +91 98765 43210",
        }
    ]
    path = tmp_path / "posts.json"
    path.write_text(json.dumps(items))
    return path

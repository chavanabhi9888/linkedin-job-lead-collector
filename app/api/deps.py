from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import Iterator

from fastapi import Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db.repositories import LeadFilter


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def require_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    expected = request.app.state.settings.api_key
    if expected is None:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, expected.get_secret_value()):
        raise HTTPException(status_code=401, detail="Invalid or missing API key", headers={"WWW-Authenticate": "ApiKey"})


def lead_filter(
    has_email: bool | None = Query(None),
    has_phone: bool | None = Query(None),
    company: str | None = Query(None, max_length=100),
    q: str | None = Query(None, max_length=100, description="Search post text, job title, author"),
    since: datetime | None = Query(None, description="Only posts dated at/after this ISO-8601 timestamp (UTC if naive)"),
    job_id: uuid.UUID | None = Query(None),
) -> LeadFilter:
    if since is not None and since.tzinfo is None:
        from datetime import timezone

        since = since.replace(tzinfo=timezone.utc)
    return LeadFilter(has_email=has_email, has_phone=has_phone, company=company, q=q, since=since, job_id=job_id)


AuthDep = Depends(require_api_key)

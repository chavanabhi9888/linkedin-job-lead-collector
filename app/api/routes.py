from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_session, lead_filter
from app.api.schemas import HealthResponse, JobResponse, LeadListResponse, RunJobRequest
from app.db.repositories import JobRepository, LeadFilter, LeadRepository
from app.domain import SearchCriteria
from app.exporters.excel import build_leads_workbook
from app.exporters.pdf import build_leads_pdf
from app.services.job_runner import JobAlreadyRunningError

logger = logging.getLogger(__name__)

health_router = APIRouter(tags=["health"])
jobs_router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[AuthDep])
leads_router = APIRouter(prefix="/leads", tags=["leads"], dependencies=[AuthDep])

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@health_router.get("/health", response_model=HealthResponse)
def health(request: Request):
    try:
        with request.app.state.session_factory() as session:
            session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        logger.exception("health_db_check_failed")
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "unavailable"})
    return HealthResponse(status="ok", database="ok")


@jobs_router.post("/run", response_model=JobResponse, status_code=202)
def run_job(body: RunJobRequest, request: Request):
    """Queue a collection run. Returns immediately; poll GET /jobs/{job_id}."""
    s = request.app.state.settings
    criteria = SearchCriteria(
        keyword=body.keyword or s.default_keyword,
        location=body.location or s.default_location,
        time_filter=body.time_filter or s.default_time_filter,
        max_posts=body.max_posts or s.default_max_posts,
    )
    try:
        job = request.app.state.runner.submit(criteria)
    except JobAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JobResponse.model_validate(job)


@jobs_router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: uuid.UUID, session: Session = Depends(get_session)):
    job = JobRepository(session).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse.model_validate(job)


@leads_router.get("", response_model=LeadListResponse)
def list_leads(
    f: LeadFilter = Depends(lead_filter),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    total, items = LeadRepository(session).list(f, limit=limit, offset=offset)
    return LeadListResponse(total=total, limit=limit, offset=offset, items=items)


def _attachment(content: bytes, media_type: str, ext: str) -> Response:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="leads_{stamp}.{ext}"'},
    )


@leads_router.get("/export/excel")
def export_excel(
    f: LeadFilter = Depends(lead_filter),
    limit: int = Query(10_000, ge=1, le=50_000),
    session: Session = Depends(get_session),
):
    return _attachment(build_leads_workbook(LeadRepository(session).all(f, limit=limit)), XLSX_MIME, "xlsx")


@leads_router.get("/export/pdf")
def export_pdf(
    f: LeadFilter = Depends(lead_filter),
    limit: int = Query(500, ge=1, le=5_000),
    session: Session = Depends(get_session),
):
    return _attachment(build_leads_pdf(LeadRepository(session).all(f, limit=limit), max_leads=limit), "application/pdf", "pdf")

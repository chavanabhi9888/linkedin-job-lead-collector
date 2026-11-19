from datetime import timedelta

from app.db.models import JobStatus
from app.db.repositories import JobRepository, LeadFilter, LeadRepository
from app.db.session import session_scope
from tests.conftest import NOW, make_lead


def _seed(session_factory):
    with session_scope(session_factory) as s:
        LeadRepository(s).add_new(
            [
                make_lead(1, email="a@acme.io", phone=None, company="Acme Tech"),
                make_lead(2, email=None, phone="+919876543210", company="Globex"),
                make_lead(3, email=None, phone=None, company="Initech", post_text="django role"),
            ]
        )


def test_filters_and_pagination(session_factory):
    _seed(session_factory)
    with session_scope(session_factory) as s:
        repo = LeadRepository(s)
        assert repo.list(LeadFilter(has_email=True))[0] == 1
        assert repo.list(LeadFilter(has_phone=True))[0] == 1
        assert repo.list(LeadFilter(has_email=False, has_phone=False))[0] == 1
        assert repo.list(LeadFilter(company="glob"))[0] == 1
        assert repo.list(LeadFilter(q="DJANGO"))[0] == 1
        assert repo.list(LeadFilter(since=NOW - timedelta(minutes=90)))[0] == 1
        total, page = repo.list(LeadFilter(), limit=2, offset=0)
        assert total == 3 and len(page) == 2
        assert page[0].post_date >= page[1].post_date  # newest first
        assert page[0].collected_at.tzinfo is not None


def test_q_filter_escapes_wildcards(session_factory):
    _seed(session_factory)
    with session_scope(session_factory) as s:
        assert LeadRepository(s).list(LeadFilter(q="%"))[0] == 0


def test_job_lifecycle_and_stale_recovery(session_factory, criteria):
    with session_scope(session_factory) as s:
        repo = JobRepository(s)
        job = repo.create(criteria)
        assert repo.active_job().id == job.id
        repo.mark_running(job.id)
        repo.add_progress(job.id, posts_seen=5, new_leads=2, emails=1)
        repo.add_progress(job.id, posts_seen=3, new_leads=1, phones=1)
    with session_scope(session_factory) as s:
        repo = JobRepository(s)
        got = repo.get(job.id)
        assert (got.status, got.posts_seen, got.new_leads, got.emails_found, got.phones_found) == (
            JobStatus.RUNNING, 8, 3, 1, 1,
        )
        assert repo.fail_stale() == 1
        assert repo.active_job() is None
        assert repo.get(job.id).error_code == "interrupted"

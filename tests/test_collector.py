from datetime import timedelta

from app.db.models import JobStatus
from app.db.repositories import JobRepository, LeadFilter, LeadRepository
from app.db.session import session_scope
from app.services.collector import CollectorService
from app.sources.base import RawPost
from app.sources.errors import ChallengeRequiredError
from tests.conftest import NOW, post_url_for


def _post(hours, text, **kw):
    return RawPost(post_url=post_url_for(NOW - timedelta(hours=hours)), text=text, author_name="A", **kw)


class FakeSource:
    name = "fake"

    def __init__(self, posts, then_raise=None):
        self.posts, self.then_raise = posts, then_raise

    def fetch_posts(self, criteria):
        yield from self.posts
        if self.then_raise:
            raise self.then_raise


def _run(session_factory, criteria, source):
    with session_scope(session_factory) as s:
        job = JobRepository(s).create(criteria)
    status = CollectorService(session_factory, lambda: source, clock=lambda: NOW).run(job.id)
    with session_scope(session_factory) as s:
        return status, JobRepository(s).get(job.id)


def test_happy_path_filters_dedupes_and_counts(session_factory, criteria):
    good = _post(2, "Hiring Python Developer in Pune. Mail hr@acme.io or call +91 98765 43210")
    posts = [
        good,
        good,                                                # exact duplicate
        _post(40, "Python Developer role, mail old@acme.io"),  # outside 24h window
        _post(3, "Looking for a chef. chef@kitchen.io"),       # keyword mismatch
        _post(4, "Python Developer opening, no contact here"),  # kept, no contact
    ]
    status, job = _run(session_factory, criteria, FakeSource(posts))
    assert status == JobStatus.SUCCEEDED
    assert (job.posts_seen, job.new_leads, job.duplicate_posts, job.skipped_posts) == (5, 2, 1, 2)
    assert (job.emails_found, job.phones_found) == (1, 1)
    with session_scope(session_factory) as s:
        total, leads = LeadRepository(s).list(LeadFilter(has_email=True))
        assert total == 1 and leads[0].phone == "+919876543210" and leads[0].job_id == job.id


def test_rerun_does_not_duplicate(session_factory, criteria):
    posts = [_post(2, "Python Developer hiring hr@acme.io")]
    _run(session_factory, criteria, FakeSource(posts))
    _, job = _run(session_factory, criteria, FakeSource(posts))
    assert (job.new_leads, job.duplicate_posts) == (0, 1)


def test_challenge_stops_job_but_keeps_partial_results(session_factory, criteria):
    source = FakeSource(
        [_post(2, "Python Developer hiring hr@acme.io")],
        then_raise=ChallengeRequiredError("captcha", screenshot_path="/tmp/x.png"),
    )
    status, job = _run(session_factory, criteria, source)
    assert status == JobStatus.NEEDS_MANUAL_ACTION
    assert job.error_code == "challenge_required" and job.new_leads == 1


def test_unexpected_error_marks_failed(session_factory, criteria):
    status, job = _run(session_factory, criteria, FakeSource([], then_raise=RuntimeError("boom")))
    assert status == JobStatus.FAILED and job.error_code == "unexpected_error"

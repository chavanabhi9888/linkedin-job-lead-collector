import pytest

from app.db.repositories import LeadRepository
from app.db.session import session_scope
from app.utils.urls import normalize_post_url
from tests.conftest import make_lead


def test_url_variants_collapse_to_one_key():
    urn = "urn:li:activity:7123456789012345678"
    variants = [
        f"https://www.linkedin.com/feed/update/{urn}/",
        f"https://linkedin.com/feed/update/{urn}?utm_source=share&trk=x",
        "https://www.linkedin.com/posts/jane-doe_python-hiring-activity-7123456789012345678-AbCd?utm_medium=ios",
    ]
    assert len({normalize_post_url(v) for v in variants}) == 1


def test_non_linkedin_url_is_stripped_of_query_and_slash():
    assert normalize_post_url("HTTPS://Example.org/p/1/?x=1#f") == "https://example.org/p/1"


@pytest.mark.parametrize("bad", ["", "   ", "ftp://x.org/a", "javascript:alert(1)"])
def test_bad_urls_rejected(bad):
    with pytest.raises(ValueError):
        normalize_post_url(bad)


def test_repository_dedup_within_and_across_batches(session_factory):
    with session_scope(session_factory) as s:
        repo = LeadRepository(s)
        first = repo.add_new([make_lead(1), make_lead(2), make_lead(1)])
        assert (len(first.inserted), first.duplicates) == (2, 1)
    with session_scope(session_factory) as s:
        second = LeadRepository(s).add_new([make_lead(2), make_lead(3)])
        assert (len(second.inserted), second.duplicates) == (1, 1)
        total, _ = LeadRepository(s).list(__import__("app.db.repositories", fromlist=["LeadFilter"]).LeadFilter())
        assert total == 3

from datetime import timedelta

import pytest

from app.domain import TimeFilter
from app.parsing.dates import (
    datetime_from_post_id,
    is_within_window,
    parse_relative_label,
    resolve_post_date,
)
from tests.conftest import NOW, post_id_for, post_url_for


@pytest.mark.parametrize(
    "label,delta",
    [
        ("2h", timedelta(hours=2)),
        ("1d", timedelta(days=1)),
        ("3w", timedelta(weeks=3)),
        ("1mo", timedelta(days=30)),
        ("5m", timedelta(minutes=5)),
        ("5 minutes ago", timedelta(minutes=5)),
        ("2 hours ago • Edited", timedelta(hours=2)),
        ("1yr", timedelta(days=365)),
    ],
)
def test_relative_labels(label, delta):
    assert parse_relative_label(label, NOW) == NOW - delta


@pytest.mark.parametrize("label", [None, "", "Promoted", "just now"])
def test_relative_label_unparseable(label):
    assert parse_relative_label(label, NOW) is None


def test_post_id_roundtrip():
    target = NOW - timedelta(hours=5)
    resolved = datetime_from_post_id(post_id_for(target), NOW)
    assert abs((resolved - target).total_seconds()) < 1


def test_implausible_ids_rejected():
    assert datetime_from_post_id(1, NOW) is None
    assert datetime_from_post_id(10**18 << 22, NOW) is None


def test_resolve_prefers_explicit_then_url_then_label():
    explicit = NOW - timedelta(hours=1)
    url = post_url_for(NOW - timedelta(hours=3))
    assert resolve_post_date(url, explicit, "9h", NOW) == explicit
    from_url = resolve_post_date(url, None, "9h", NOW)
    assert abs((from_url - (NOW - timedelta(hours=3))).total_seconds()) < 1
    assert resolve_post_date("https://example.org/p/1", None, "9h", NOW) == NOW - timedelta(hours=9)


class TestWindow:
    def test_24h(self):
        assert is_within_window(NOW - timedelta(hours=23), TimeFilter.PAST_24H, NOW)
        assert not is_within_window(NOW - timedelta(hours=30), TimeFilter.PAST_24H, NOW)

    def test_week(self):
        assert is_within_window(NOW - timedelta(days=6), TimeFilter.PAST_WEEK, NOW)
        assert not is_within_window(NOW - timedelta(days=8), TimeFilter.PAST_WEEK, NOW)

    def test_unknown_date_policy(self):
        assert is_within_window(None, TimeFilter.PAST_24H, NOW)
        assert not is_within_window(None, TimeFilter.PAST_24H, NOW, allow_unknown=False)

    def test_far_future_rejected(self):
        assert not is_within_window(NOW + timedelta(days=2), TimeFilter.PAST_WEEK, NOW)

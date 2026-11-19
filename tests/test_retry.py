import pytest

from app.sources.errors import AuthenticationError, SourceTimeoutError
from app.utils.retry import call_with_retries


def test_retries_retryable_errors_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise SourceTimeoutError("slow")
        return "ok"

    assert call_with_retries(flaky, max_attempts=3, description="t", sleep=lambda s: None) == "ok"
    assert calls["n"] == 3


def test_gives_up_after_max_attempts():
    def always():
        raise SourceTimeoutError("slow")

    with pytest.raises(SourceTimeoutError):
        call_with_retries(always, max_attempts=2, description="t", sleep=lambda s: None)


def test_non_retryable_is_not_retried():
    calls = {"n": 0}

    def bad():
        calls["n"] += 1
        raise AuthenticationError("nope")

    with pytest.raises(AuthenticationError):
        call_with_retries(bad, max_attempts=5, description="t", sleep=lambda s: None)
    assert calls["n"] == 1

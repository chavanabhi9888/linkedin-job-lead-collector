"""Error taxonomy raised by any lead source.

``retryable`` errors are retried with backoff; everything else stops the job
immediately (we never try to get around a CAPTCHA/MFA/rate-limit signal).
"""
from __future__ import annotations


class SourceError(Exception):
    retryable = False
    code = "source_error"

    def __init__(self, message: str, *, screenshot_path: str | None = None) -> None:
        super().__init__(message)
        self.screenshot_path = screenshot_path


class SourceConfigurationError(SourceError):
    code = "configuration_error"


class AuthenticationError(SourceError):
    code = "login_failed"


class ChallengeRequiredError(SourceError):
    """CAPTCHA / MFA / security checkpoint. A human must resolve it; we stop."""

    code = "challenge_required"


class RateLimitedError(SourceError):
    code = "rate_limited"


class LayoutChangedError(SourceError):
    code = "layout_changed"


class SourceTimeoutError(SourceError):
    retryable = True
    code = "timeout"


class SourceNetworkError(SourceError):
    retryable = True
    code = "network_error"

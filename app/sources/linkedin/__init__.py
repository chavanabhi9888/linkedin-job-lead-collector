"""LinkedIn browser source. Replace this package to change data provider."""
from __future__ import annotations

import logging
from typing import Iterator

from app.config import Settings
from app.domain import SearchCriteria
from app.sources.base import RawPost
from app.sources.linkedin.auth import LinkedInAuthenticator
from app.sources.linkedin.browser import BrowserSession
from app.sources.linkedin.search import LinkedInPostSearch
from app.utils.rate_limit import RateLimiter
from app.utils.retry import call_with_retries

logger = logging.getLogger(__name__)

__all__ = ["LinkedInSource"]


class LinkedInSource:
    name = "linkedin"

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def fetch_posts(self, criteria: SearchCriteria) -> Iterator[RawPost]:
        limiter = RateLimiter(self._s.min_action_delay_s, self._s.max_action_delay_s)
        with BrowserSession(self._s) as browser:
            auth = LinkedInAuthenticator(browser, self._s, limiter)
            call_with_retries(auth.ensure_logged_in, max_attempts=self._s.max_retries, description="login")
            yield from LinkedInPostSearch(browser, self._s, limiter).iter_posts(criteria)

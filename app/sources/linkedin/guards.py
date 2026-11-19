"""Page-state checks and Playwright->SourceError translation."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.sources.errors import (
    ChallengeRequiredError,
    SourceError,
    SourceNetworkError,
    SourceTimeoutError,
)
from app.sources.linkedin import selectors
from app.sources.linkedin.browser import BrowserSession

logger = logging.getLogger(__name__)
_NETWORK_MARKERS = ("net::", "NS_ERROR", "ERR_", "Connection refused", "Connection reset")


def has_session_cookie(page: Page) -> bool:
    """LinkedIn sets the ``li_at`` cookie once authentication fully completes.

    Markup-independent, so it keeps working when LinkedIn changes its page layout.
    """
    try:
        cookies = page.context.cookies("https://www.linkedin.com")
    except PlaywrightError:
        return False
    return any(c["name"] == "li_at" and c.get("value") for c in cookies)


def is_logged_in(page: Page) -> bool:
    url = page.url
    if any(part in url for part in selectors.NOT_LOGGED_IN_URL_PARTS + selectors.CHALLENGE_URL_PARTS):
        return False
    return has_session_cookie(page) or page.locator(selectors.LOGGED_IN_MARKER).count() > 0


def detect_challenge(page: Page) -> str | None:
    """Return a short reason if LinkedIn is asking for human verification."""
    url = page.url.lower()
    if any(part in url for part in selectors.CHALLENGE_URL_PARTS):
        return "challenge URL"
    try:
        if page.locator(selectors.CHALLENGE_SELECTORS).count() > 0:
            return "CAPTCHA/verification element"
        body = (page.inner_text("body", timeout=3000) or "")[:4000].lower()
    except PlaywrightError:
        return None
    return "verification text" if any(t in body for t in selectors.CHALLENGE_TEXT) else None


def raise_if_challenge(browser: BrowserSession, step: str) -> None:
    reason = detect_challenge(browser.page)
    if reason:
        logger.warning("challenge_detected", extra={"step": step, "reason": reason})
        raise ChallengeRequiredError(
            f"LinkedIn requested human verification ({reason}). Resolve it manually with "
            "`python -m app.cli login`, then re-run. The collector will not bypass it.",
            screenshot_path=browser.screenshot(f"{step}_challenge"),
        )


@contextmanager
def translate_errors(browser: BrowserSession, step: str) -> Iterator[None]:
    """Convert Playwright errors into SourceError subclasses; screenshot on failure."""
    try:
        yield
    except SourceError:
        raise
    except PlaywrightTimeoutError as exc:
        raise SourceTimeoutError(
            f"Timed out during '{step}'", screenshot_path=browser.screenshot(f"{step}_timeout")
        ) from exc
    except PlaywrightError as exc:
        shot = browser.screenshot(f"{step}_error")
        if any(marker in str(exc) for marker in _NETWORK_MARKERS):
            raise SourceNetworkError(f"Network error during '{step}'", screenshot_path=shot) from exc
        raise SourceError(f"Browser error during '{step}': {str(exc)[:200]}", screenshot_path=shot) from exc

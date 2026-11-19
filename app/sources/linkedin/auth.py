"""Normal LinkedIn login flow. Stops (never bypasses) on CAPTCHA / MFA."""
from __future__ import annotations

import logging
import time

from app.config import Settings
from app.sources.errors import AuthenticationError
from app.sources.linkedin import selectors
from app.sources.linkedin.browser import BrowserSession
from app.sources.linkedin.guards import (
    has_session_cookie,
    is_logged_in,
    raise_if_challenge,
    translate_errors,
)
from app.utils.rate_limit import RateLimiter

logger = logging.getLogger(__name__)


class LinkedInAuthenticator:
    def __init__(self, browser: BrowserSession, settings: Settings, limiter: RateLimiter) -> None:
        self._browser, self._s, self._limiter = browser, settings, limiter

    def ensure_logged_in(self) -> None:
        with translate_errors(self._browser, "ensure_logged_in"):
            page = self._browser.page
            page.goto(selectors.FEED_URL, wait_until="domcontentloaded")
            self._limiter.wait()
            raise_if_challenge(self._browser, "session_check")
            if is_logged_in(page):
                logger.info("session_reused")
                return
            self._login_with_credentials()

    def _login_with_credentials(self) -> None:
        page = self._browser.page
        if not self._s.linkedin_email or not self._s.linkedin_password:
            raise AuthenticationError(
                "No valid saved session and LINKEDIN_EMAIL/LINKEDIN_PASSWORD are not set. "
                "Run `python -m app.cli login` once to sign in interactively.",
                screenshot_path=self._browser.screenshot("no_credentials"),
            )
        logger.info("login_started")
        page.goto(selectors.LOGIN_URL, wait_until="domcontentloaded")
        page.fill(selectors.LOGIN_USERNAME, self._s.linkedin_email)
        self._limiter.wait()
        page.fill(selectors.LOGIN_PASSWORD, self._s.linkedin_password.get_secret_value())
        self._limiter.wait()
        page.click(selectors.LOGIN_SUBMIT)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2500)  # allow redirects to settle

        raise_if_challenge(self._browser, "login")  # CAPTCHA / MFA -> stop
        if page.locator(selectors.LOGIN_ERRORS).count() > 0:
            raise AuthenticationError(
                "LinkedIn rejected the supplied credentials.",
                screenshot_path=self._browser.screenshot("login_rejected"),
            )
        if not is_logged_in(page):
            raise AuthenticationError(
                "Login did not complete (unexpected page after submit).",
                screenshot_path=self._browser.screenshot("login_incomplete"),
            )
        self._browser.save_state()
        logger.info("login_succeeded")


def interactive_login(settings: Settings, timeout_s: int = 300) -> bool:
    """Open a visible browser; the human signs in (and solves any CAPTCHA/MFA)."""
    visible = settings.model_copy(update={"browser_headless": False})
    with BrowserSession(visible) as browser:
        page = browser.page
        page.goto(selectors.LOGIN_URL, wait_until="domcontentloaded")
        print(f"Sign in to LinkedIn in the opened browser window (waiting up to {timeout_s}s)...")
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if is_logged_in(page):
                browser.save_state()
                return True
            page.wait_for_timeout(1000)
        path = page.url.split("?")[0]
        print(f"Timed out. Last page: {path} | session cookie present: {has_session_cookie(page)}")
    return False

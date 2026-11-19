"""Playwright session wrapper: persistent session file, screenshots on failure.

No stealth plugins, no fingerprint spoofing, no proxy rotation: we behave like an
ordinary browser and stop when LinkedIn asks for human verification.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)

from app.config import Settings

logger = logging.getLogger(__name__)


class BrowserSession:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page = None  # type: ignore[assignment]

    def __enter__(self) -> "BrowserSession":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._s.browser_headless)
        kwargs: dict = {"viewport": {"width": 1366, "height": 900}, "locale": "en-US"}
        state = Path(self._s.linkedin_storage_state)
        if state.is_file():
            kwargs["storage_state"] = str(state)
            logger.info("browser_session_state_loaded")
        self._context = self._browser.new_context(**kwargs)
        self._context.set_default_timeout(self._s.nav_timeout_ms)
        self._context.set_default_navigation_timeout(self._s.nav_timeout_ms)
        self.page = self._context.new_page()
        return self

    def __exit__(self, *exc) -> None:
        for closer in (
            lambda: self._context and self._context.close(),
            lambda: self._browser and self._browser.close(),
            lambda: self._pw and self._pw.stop(),
        ):
            try:
                closer()
            except Exception:  # noqa: BLE001 - best-effort teardown
                logger.debug("browser_teardown_error", exc_info=True)

    def save_state(self) -> None:
        path = Path(self._s.linkedin_storage_state)
        path.parent.mkdir(parents=True, exist_ok=True)
        assert self._context is not None
        self._context.storage_state(path=str(path))
        os.chmod(path, 0o600)  # contains session cookies
        logger.info("browser_session_state_saved")

    def screenshot(self, step: str) -> str | None:
        """Capture the current page for post-mortem. Never raises."""
        try:
            directory = Path(self._s.screenshot_dir)
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            path = directory / f"{stamp}_{step}.png"
            self.page.screenshot(path=str(path))
            logger.info("screenshot_saved", extra={"step": step, "path": str(path)})
            return str(path)
        except Exception:  # noqa: BLE001
            logger.warning("screenshot_failed", extra={"step": step})
            return None

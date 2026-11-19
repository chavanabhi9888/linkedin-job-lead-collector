"""Search LinkedIn content for recent posts and read what is visible on the page."""
from __future__ import annotations

import json
import logging
from typing import Any, Iterator
from urllib.parse import urlencode

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.config import Settings
from app.domain import SearchCriteria, TimeFilter
from app.sources.base import RawPost
from app.sources.errors import SourceTimeoutError
from app.sources.linkedin import selectors
from app.sources.linkedin.browser import BrowserSession
from app.sources.linkedin.guards import raise_if_challenge, translate_errors
from app.utils.rate_limit import RateLimiter
from app.utils.retry import call_with_retries

logger = logging.getLogger(__name__)

_DATE_FILTER = {
    TimeFilter.PAST_24H: "past-24h",
    TimeFilter.PAST_WEEK: "past-week",
}


class LinkedInPostSearch:
    def __init__(self, browser: BrowserSession, settings: Settings, limiter: RateLimiter) -> None:
        self._browser, self._s, self._limiter = browser, settings, limiter

    @staticmethod
    def build_search_url(criteria: SearchCriteria) -> str:
        params = {
            "keywords": f"{criteria.keyword} {criteria.location}".strip(),
            "origin": "FACETED_SEARCH",
            "datePosted": json.dumps(_DATE_FILTER[criteria.time_filter]),
            "sortBy": json.dumps("date_posted"),
        }
        return f"{selectors.SEARCH_URL}?{urlencode(params)}"

    def iter_posts(self, criteria: SearchCriteria) -> Iterator[RawPost]:
        call_with_retries(
            self._open_results,
            self.build_search_url(criteria),
            max_attempts=self._s.max_retries,
            description="open_results",
        )
        page = self._browser.page
        if page.locator(selectors.NO_RESULTS).count() > 0 and page.locator(selectors.POST_CARD).count() == 0:
            logger.info("search_returned_no_results")
            return

        seen: set[str] = set()
        stagnant = yielded = 0

        for scroll in range(self._s.max_scrolls):
            with translate_errors(self._browser, "read_results"):
                raise_if_challenge(self._browser, "read_results")
                self._expand_see_more()
                cards = page.eval_on_selector_all(selectors.POST_CARD, selectors.EXTRACT_POSTS_JS)

            fresh = [
                c for c in cards 
                if (c.get("post_url") or c.get("urn")) 
                and (c.get("post_url") or c.get("urn")) not in seen
            ]

            for card in fresh:
                dedup_key = card.get("post_url") or card.get("urn")
                seen.add(dedup_key)
                post = self._to_raw_post(card)
                if post:
                    yielded += 1
                    yield post
                    if yielded >= criteria.max_posts:
                        logger.info("max_posts_reached", extra={"count": yielded})
                        return

            stagnant = 0 if fresh else stagnant + 1
            if stagnant >= 3:
                logger.info("feed_reached_end", extra={"yielded": yielded, "scrolls": scroll + 1})
                break

            self._scroll_page()
            self._limiter.wait()

        logger.info("search_finished", extra={"count": yielded, "scrolls": scroll + 1})

    def _open_results(self, url: str) -> None:
        page = self._browser.page
        with translate_errors(self._browser, "open_results"):
            page.goto(url, wait_until="domcontentloaded")
            self._limiter.wait()
            raise_if_challenge(self._browser, "open_results")
            try:
                page.wait_for_selector("main", timeout=self._s.nav_timeout_ms)
                page.wait_for_timeout(3500)
            except PlaywrightTimeoutError:
                shot = self._browser.screenshot("results_not_found")
                raise SourceTimeoutError("Search page did not load in time.", screenshot_path=shot)

    def _scroll_page(self) -> None:
        """Deep scroll targeting LinkedIn's virtualized list and internal containers."""
        page = self._browser.page
        with translate_errors(self._browser, "scroll"):
            # 1. Scroll last visible card into view (forces lazy list to load more)
            cards = page.locator(selectors.POST_CARD)
            count = cards.count()
            if count > 0:
                try:
                    cards.nth(count - 1).scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass

            # 2. Scroll any scrollable container in DOM
            page.evaluate("""
            () => {
                window.scrollBy(0, 2500);
                window.scrollTo(0, document.body.scrollHeight);
                const all = document.querySelectorAll('main, #workspace, [data-testid="lazy-column"], div');
                for (const el of all) {
                    if (el.scrollHeight > el.clientHeight && el.clientHeight > 250) {
                        el.scrollTop = el.scrollHeight;
                    }
                }
            }
            """)

            # 3. Trigger wheel and PageDown events
            page.mouse.wheel(0, 3500)
            page.keyboard.press("PageDown")

            # 4. Wait for background GraphQL request to return new posts
            page.wait_for_timeout(2500)

    def _expand_see_more(self) -> None:
        """Click every '... more' button directly in DOM to reveal full post text."""
        try:
            self._browser.page.evaluate("""
            () => {
                const candidates = document.querySelectorAll('button, [role="button"], span, a');
                for (const el of candidates) {
                    const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                    if (
                        text === '... more' || 
                        text === 'more' || 
                        text.endsWith('... more') || 
                        text.includes('see more')
                    ) {
                        try {
                            el.click();
                        } catch (e) {}
                    }
                }
            }
            """)
            self._browser.page.wait_for_timeout(800)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _to_raw_post(card: dict[str, Any]) -> RawPost | None:
        post_url = card.get("post_url")
        urn = card.get("urn", "")
        if not post_url and urn.startswith("urn:li:"):
            post_url = f"{selectors.BASE_URL}/feed/update/{urn}/"
        if not post_url:
            return None

        author = (card.get("author") or "").splitlines()
        return RawPost(
            post_url=post_url,
            text=card.get("text") or "",
            author_name=author[0].strip() if author else None,
            profile_url=card.get("profile") or None,
            posted_label=((card.get("label") or "").split("•")[0].strip() or None),
        )
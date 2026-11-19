"""Retry with exponential backoff, only for errors flagged ``retryable``."""
from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.sources.errors import SourceError

logger = logging.getLogger(__name__)
T = TypeVar("T")


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, SourceError) and exc.retryable


def call_with_retries(
    fn: Callable[..., T],
    *args,
    max_attempts: int,
    description: str,
    base_delay: float = 3.0,
    max_delay: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs,
) -> T:
    def _before_sleep(state: RetryCallState) -> None:
        exc = state.outcome.exception() if state.outcome else None
        logger.warning(
            "retrying_after_error",
            extra={
                "step": description,
                "attempt": state.attempt_number,
                "max_attempts": max_attempts,
                "error_code": getattr(exc, "code", type(exc).__name__),
            },
        )

    retrying = Retrying(
        stop=stop_after_attempt(max(1, max_attempts)),
        wait=wait_exponential_jitter(initial=base_delay, max=max_delay),
        retry=retry_if_exception(_is_retryable),
        before_sleep=_before_sleep,
        sleep=sleep,
        reraise=True,
    )
    return retrying(fn, *args, **kwargs)

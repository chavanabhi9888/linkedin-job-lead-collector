"""Conservative, jittered pacing between browser actions."""
from __future__ import annotations

import random
import time
from typing import Callable


class RateLimiter:
    def __init__(
        self,
        min_delay: float,
        max_delay: float,
        *,
        sleep: Callable[[float], None] = time.sleep,
        uniform: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._min, self._max, self._sleep, self._uniform = min_delay, max_delay, sleep, uniform

    def wait(self) -> float:
        delay = self._uniform(self._min, self._max)
        self._sleep(delay)
        return delay

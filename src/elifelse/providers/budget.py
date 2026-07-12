"""Daily token budget across ALL calls (background included).

A 24/7 autonomous agent on a metered API without a cap is the #1 way to hurt a
user. When the cap is hit, the controller auto-sleeps the agent until the daily
reset and says why. 0 = unlimited (the wizard makes you choose that deliberately).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta


class TokenBudget:
    def __init__(self, daily_limit: int = 0, clock: Callable[[], datetime] = datetime.now) -> None:
        self.daily_limit = daily_limit
        self._clock = clock
        self.used = 0
        self._day = self._clock().date()

    def _roll(self) -> None:
        today = self._clock().date()
        if today != self._day:
            self._day = today
            self.used = 0

    def record(self, tokens: int) -> None:
        self._roll()
        self.used += max(0, tokens)

    @property
    def exceeded(self) -> bool:
        self._roll()
        return self.daily_limit > 0 and self.used >= self.daily_limit

    @property
    def remaining(self) -> int | None:
        """None = unlimited."""
        self._roll()
        if self.daily_limit <= 0:
            return None
        return max(0, self.daily_limit - self.used)

    def seconds_until_reset(self) -> float:
        now = self._clock()
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return (tomorrow - now).total_seconds()

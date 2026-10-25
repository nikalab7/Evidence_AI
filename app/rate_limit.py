"""Process-local investigation quotas with atomic reservation under concurrency."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import ceil
from threading import Lock
from time import monotonic


@dataclass(frozen=True)
class LimitRejection:
    reason: str
    retry_after_seconds: int


class InvestigationLimiter:
    """Atomic per-IP, daily, and concurrent limits for one app process only."""

    def __init__(
        self,
        *,
        daily_budget: int,
        per_ip_per_minute: int,
        max_concurrent: int,
        window_seconds: int = 60,
    ) -> None:
        if daily_budget < 0 or per_ip_per_minute < 1 or max_concurrent < 1:
            raise ValueError("investigation limits are outside their valid range")
        self.daily_budget = daily_budget
        self.per_ip_per_minute = per_ip_per_minute
        self.max_concurrent = max_concurrent
        self.window_seconds = window_seconds
        self._lock = Lock()
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._utc_day = datetime.now(timezone.utc).date()
        self._daily_count = 0
        self._active = 0
        self._reservation_count = 0

    def reserve(self, client_ip: str, *, now: float | None = None,
                utc_day: date | None = None) -> LimitRejection | None:
        """Atomically consume one daily slot and return None when it is reserved."""
        current_time = monotonic() if now is None else now
        current_day = datetime.now(timezone.utc).date() if utc_day is None else utc_day
        with self._lock:
            if current_day != self._utc_day:
                self._utc_day = current_day
                self._daily_count = 0
                self._requests.clear()
            if self.daily_budget == 0:
                return LimitRejection("disabled", 0)

            self._reservation_count += 1
            if self._reservation_count % 128 == 0:
                stale_before = current_time - self.window_seconds
                for known_ip, history in list(self._requests.items()):
                    while history and history[0] <= stale_before:
                        history.popleft()
                    if not history:
                        del self._requests[known_ip]

            requests = self._requests[client_ip]
            cutoff = current_time - self.window_seconds
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= self.per_ip_per_minute:
                wait = max(1, ceil(self.window_seconds - (current_time - requests[0])))
                return LimitRejection("per_ip", wait)
            if self._daily_count >= self.daily_budget:
                tomorrow = datetime.combine(
                    current_day, datetime.min.time(), tzinfo=timezone.utc,
                ).timestamp() + 86_400
                return LimitRejection("daily", max(1, ceil(tomorrow - datetime.now(timezone.utc).timestamp())))
            if self._active >= self.max_concurrent:
                return LimitRejection("concurrent", 5)

            requests.append(current_time)
            self._daily_count += 1
            self._active += 1
            return None

    def release(self) -> None:
        """Release a concurrent slot; the daily reservation is never refunded."""
        with self._lock:
            if self._active > 0:
                self._active -= 1

    def snapshot(self) -> dict[str, int]:
        """Return non-sensitive process-local counters for tests and internal logs."""
        with self._lock:
            return {"daily_reserved": self._daily_count, "active": self._active}

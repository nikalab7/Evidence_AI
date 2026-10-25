"""Sanitized process RSS sampling while investigation requests are active."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from threading import Event, Lock, Thread
from time import sleep
from typing import Callable, Iterator

from app.embedding_smoke import process_rss_bytes


@dataclass
class RequestMemorySample:
    rss_before_bytes: int | None
    peak_rss_bytes: int | None
    rss_after_bytes: int | None = None
    concurrent_at_start: int = 0
    peak_concurrent: int = 0

    def as_dict(self) -> dict[str, int | None]:
        growth = (
            self.rss_after_bytes - self.rss_before_bytes
            if self.rss_before_bytes is not None and self.rss_after_bytes is not None
            else None
        )
        return {
            "rss_before_bytes": self.rss_before_bytes,
            "rss_after_bytes": self.rss_after_bytes,
            "peak_rss_bytes": self.peak_rss_bytes,
            "rss_growth_bytes": growth,
            "concurrent_at_start": self.concurrent_at_start,
            "peak_concurrent_investigations": self.peak_concurrent,
        }


class ProcessMemoryMonitor:
    """Sample RSS at 50 ms only while one or more investigations are running."""

    def __init__(
        self,
        *,
        rss_reader: Callable[[], int | None] = process_rss_bytes,
        sample_interval_seconds: float = 0.05,
    ) -> None:
        self._rss_reader = rss_reader
        self._sample_interval_seconds = sample_interval_seconds
        self.startup_rss_bytes = rss_reader()
        self._lock = Lock()
        self._active: dict[int, RequestMemorySample] = {}
        self._next_id = 0
        self._sampling = Event()
        self._shutdown = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(target=self._sample_loop, name="evidenceai-rss", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._shutdown.set()
        self._sampling.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    @contextmanager
    def track(self) -> Iterator[RequestMemorySample]:
        rss_before = self._rss_reader()
        with self._lock:
            self._next_id += 1
            sample_id = self._next_id
            sample = RequestMemorySample(
                rss_before_bytes=rss_before,
                peak_rss_bytes=rss_before,
                concurrent_at_start=len(self._active) + 1,
                peak_concurrent=len(self._active) + 1,
            )
            self._active[sample_id] = sample
            for active_sample in self._active.values():
                active_sample.peak_concurrent = max(
                    active_sample.peak_concurrent, len(self._active),
                )
            self._sampling.set()
        try:
            yield sample
        finally:
            rss_after = self._rss_reader()
            with self._lock:
                sample.rss_after_bytes = rss_after
                if rss_after is not None:
                    sample.peak_rss_bytes = max(sample.peak_rss_bytes or rss_after, rss_after)
                self._active.pop(sample_id, None)
                if not self._active:
                    self._sampling.clear()

    def _sample_loop(self) -> None:
        while not self._shutdown.is_set():
            self._sampling.wait()
            if self._shutdown.is_set():
                return
            while self._sampling.is_set() and not self._shutdown.is_set():
                rss = self._rss_reader()
                if rss is not None:
                    with self._lock:
                        for sample in self._active.values():
                            sample.peak_rss_bytes = max(sample.peak_rss_bytes or rss, rss)
                sleep(self._sample_interval_seconds)

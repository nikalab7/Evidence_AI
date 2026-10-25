from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier, Event, Lock, Thread
from time import sleep

from app.memory_monitor import ProcessMemoryMonitor
from app.rate_limit import InvestigationLimiter


def test_daily_reservations_are_atomic_under_concurrent_requests():
    limiter = InvestigationLimiter(
        daily_budget=3, per_ip_per_minute=20, max_concurrent=10,
    )
    barrier = Barrier(10)

    def reserve(index):
        barrier.wait()
        return limiter.reserve(f"client-{index}")

    with ThreadPoolExecutor(max_workers=10) as pool:
        outcomes = list(pool.map(reserve, range(10)))

    assert outcomes.count(None) == 3
    assert sum(item is not None and item.reason == "daily" for item in outcomes) == 7
    assert limiter.snapshot() == {"daily_reserved": 3, "active": 3}


def test_rate_concurrency_and_utc_day_limits_have_clear_reasons():
    limiter = InvestigationLimiter(
        daily_budget=2, per_ip_per_minute=1, max_concurrent=1,
    )
    today = date(2026, 10, 25)
    assert limiter.reserve("one", now=10, utc_day=today) is None
    assert limiter.reserve("two", now=11, utc_day=today).reason == "concurrent"
    limiter.release()
    assert limiter.reserve("one", now=12, utc_day=today).reason == "per_ip"
    assert limiter.reserve("two", now=12, utc_day=today) is None
    limiter.release()
    assert limiter.reserve("three", now=13, utc_day=today).reason == "daily"
    assert limiter.reserve("three", now=14, utc_day=today + timedelta(days=1)) is None
    limiter.release()


def test_zero_daily_budget_fails_closed():
    limiter = InvestigationLimiter(daily_budget=0, per_ip_per_minute=2, max_concurrent=1)
    assert limiter.reserve("client").reason == "disabled"
    assert limiter.snapshot() == {"daily_reserved": 0, "active": 0}


def test_process_memory_monitor_records_request_growth_and_peak():
    rss = [100]
    monitor = ProcessMemoryMonitor(rss_reader=lambda: rss[0], sample_interval_seconds=0.005)
    monitor.start()
    try:
        with monitor.track() as sample:
            rss[0] = 120
            sleep(0.02)
            rss[0] = 180
            sleep(0.02)
        assert sample.as_dict() == {
            "rss_before_bytes": 100,
            "rss_after_bytes": 180,
            "peak_rss_bytes": 180,
            "rss_growth_bytes": 80,
            "concurrent_at_start": 1,
            "peak_concurrent_investigations": 1,
        }
    finally:
        monitor.stop()


def test_memory_monitor_records_two_overlapping_investigations():
    monitor = ProcessMemoryMonitor(rss_reader=lambda: 128, sample_interval_seconds=0.005)
    monitor.start()
    both_active = Event()
    count_lock = Lock()
    entered = [0]
    release = Event()
    samples = []

    def run_one():
        with monitor.track() as sample:
            samples.append(sample)
            with count_lock:
                entered[0] += 1
                if entered[0] == 2:
                    both_active.set()
            release.wait(timeout=2)

    workers = [Thread(target=run_one) for _ in range(2)]
    try:
        for worker in workers:
            worker.start()
        assert both_active.wait(timeout=2)
        sleep(0.015)
        release.set()
        for worker in workers:
            worker.join(timeout=2)
        assert len(samples) == 2
        assert all(sample.as_dict()["peak_concurrent_investigations"] == 2 for sample in samples)
        assert all(sample.as_dict()["peak_rss_bytes"] == 128 for sample in samples)
    finally:
        release.set()
        for worker in workers:
            if worker.is_alive():
                worker.join(timeout=2)
        monitor.stop()

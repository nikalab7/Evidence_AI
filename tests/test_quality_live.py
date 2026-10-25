import json

import pytest

from app.config import Settings
from app.evaluation import quality_live
from app.evaluation.quality_dev import load_cases
from app.llm.gemini_client import GeminiAPIError
from app.llm.schemas import LLMResponse


def _settings(budget=60):
    return Settings(gemini_api_key="test-only", investigation_daily_budget=budget,
                    database_url="postgresql://test@db.nldnpqhqrfwjgxcqeuru.supabase.co/postgres")


def _isolated_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(quality_live, "ROOT", tmp_path)
    monkeypatch.setattr(quality_live, "DEFAULT_LEDGER", tmp_path / "ledger.jsonl")


def test_exhausted_existing_ledger_prevents_any_development_api_call(monkeypatch, tmp_path):
    _isolated_paths(monkeypatch, tmp_path)
    quality_live.reserve_investigation(quality_live.DEFAULT_LEDGER, run_key="old-final-key",
                                      case_id="old", mode="semantic", daily_budget=1)
    monkeypatch.setattr(quality_live, "GeminiClient", lambda *_a, **_k: pytest.fail("budget bypass"))
    fixtures = [c for c in load_cases()[0] if c["execution_mode"] == "fixture"]
    output = quality_live.run_live_comparison(fixtures, variant="after", settings=_settings(1),
                                              max_investigations=10)
    assert output["completed_this_run"] == 0
    assert output["requests_this_run"] == 0
    assert output["stop_reason"] == "local_rolling_budget_reached"
    assert len(quality_live.DEFAULT_LEDGER.read_text().splitlines()) == 1


def test_quota_stops_development_run_and_preserves_all_attempt_metrics(monkeypatch, tmp_path):
    _isolated_paths(monkeypatch, tmp_path)
    called = []

    class Client:
        def __init__(self, settings, **kwargs):
            self.settings = settings
            self.calls = 0
            assert kwargs["stop_on_rate_limit"] is True

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def generate(self, **_kwargs):
            self.calls += 1
            metric = {"latency_seconds": .01, "http_status": 200 if self.calls == 1 else 429}
            if self.calls == 2:
                raise GeminiAPIError("provider_quota_exhausted", [metric], status=429)
            return LLMResponse("ready", [], {"parts": []}, [metric])

    def quota_case(case, **kwargs):
        called.append(case["case_id"])
        kwargs["tracked"].generate()
        kwargs["tracked"].generate()

    monkeypatch.setattr(quality_live, "GeminiClient", Client)
    monkeypatch.setattr(quality_live, "run_case", quota_case)
    fixtures = [c for c in load_cases()[0] if c["execution_mode"] == "fixture"]
    output = quality_live.run_live_comparison(fixtures, variant="after", settings=_settings(),
                                              max_investigations=10)
    assert called == [fixtures[0]["case_id"]]
    assert output["stop_reason"] == "provider_quota"
    assert output["requests_this_run"] == 2
    results_path = tmp_path / "reports/quality_dev_after_results.jsonl"
    rows = [json.loads(line) for line in results_path.read_text().splitlines()]
    assert rows[0]["api_request_count"] == 2
    assert rows[0]["error_type"] == "GeminiAPIError"
    # Simulate an interrupted journal write in isolated resources, preserving its reservation.
    results_path.write_text("")
    with pytest.raises(RuntimeError, match="uncertain development reservation"):
        quality_live.run_live_comparison(fixtures, variant="after", settings=_settings(),
                                         max_investigations=10)
    assert len(called) == 1


def test_live_case_uses_read_only_session_and_closes_it_on_agent_failure(monkeypatch):
    statements = []

    class Connection:
        closed = False

        def execute(self, sql):
            statements.append(sql)

        def close(self):
            self.closed = True

    conn = Connection()

    def connect(**kwargs):
        assert kwargs == {"autocommit": True}
        return conn

    def fail(**kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(quality_live, "connect_database", connect)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        quality_live.run_case({"question": "Test question?", "execution_mode": "live"},
                              settings=_settings(), model=object(),
                              agent=lambda *_a, **kwargs: fail(**kwargs), tracked=object())
    assert conn.closed
    assert statements == ["SET default_transaction_read_only = on"]


def test_wrong_database_identity_fails_before_any_live_work(monkeypatch, tmp_path):
    _isolated_paths(monkeypatch, tmp_path)
    settings = Settings(gemini_api_key="test-only", investigation_daily_budget=60,
                        database_url="postgresql://test@db.other-project.supabase.co/postgres")
    with pytest.raises(RuntimeError, match="approved Frankfurt"):
        quality_live.run_live_comparison([], variant="after", settings=settings, max_investigations=1)
    assert not quality_live.DEFAULT_LEDGER.exists()


def test_tracked_client_refuses_a_sixth_http_attempt():
    class Client:
        settings = _settings()

        def __init__(self):
            self.calls = 0

        def generate(self, **kwargs):
            self.calls += 1
            assert kwargs["request_budget"] <= 6 - self.calls
            return LLMResponse("ok", [], {}, [{"latency_seconds": .01}])

    client = Client()
    tracked = quality_live.TrackedClient(client)
    for _ in range(5):
        tracked.generate(request_budget=5)
    with pytest.raises(GeminiAPIError, match="request_budget_exhausted"):
        tracked.generate(request_budget=5)
    assert client.calls == 5

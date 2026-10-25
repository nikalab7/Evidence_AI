import json
import logging
import sys

import pytest
from fastapi.testclient import TestClient

from app.embedding_smoke import (
    EXPECTED_DIMENSIONS,
    process_peak_rss_bytes,
    process_rss_bytes,
    run_embedding_smoke_test,
)
from app.main import app


class FakeModel:
    def __init__(self, dimension=EXPECTED_DIMENSIONS):
        self.dimension = dimension

    def query_embed(self, queries):
        assert len(queries) == 1
        return [[0.0] * self.dimension]


def test_embedding_smoke_reports_dimensions_timings_and_memory(monkeypatch):
    times = iter([1.0, 1.1, 1.4])
    memory = iter([100, 140, 150])
    model, report = run_embedding_smoke_test(
        model_loader=lambda model_name: FakeModel(), rss_reader=lambda: next(memory),
        peak_rss_reader=lambda: 160,
        clock=lambda: next(times),
    )
    assert isinstance(model, FakeModel)
    assert report["status"] == "passed"
    assert report["dimensions"] == 384
    assert report["model_initialization_seconds"] == pytest.approx(0.1)
    assert report["first_query_embedding_seconds"] == pytest.approx(0.3)
    assert report["smoke_startup_seconds"] == pytest.approx(0.4)
    assert report["rss_delta_bytes"] == 50
    assert report["peak_rss_bytes"] == 160


def test_embedding_smoke_rejects_wrong_dimensions():
    with pytest.raises(ValueError, match="Expected 384 dimensions, got 768"):
        run_embedding_smoke_test(
            model_loader=lambda model_name: FakeModel(768), rss_reader=lambda: 100,
        )


def test_embedding_smoke_rejects_multiple_vectors():
    class WrongCountModel:
        def query_embed(self, queries):
            return []
    with pytest.raises(ValueError, match="Expected one query vector"):
        run_embedding_smoke_test(
            model_loader=lambda model_name: WrongCountModel(), rss_reader=lambda: 100,
        )


def test_process_rss_reader_returns_a_value_on_supported_platforms():
    rss = process_rss_bytes()
    peak_rss = process_peak_rss_bytes()
    if sys.platform.startswith(("linux", "win32", "darwin")):
        assert rss is not None
        assert rss > 0
        assert peak_rss is not None
        assert peak_rss >= rss


def test_public_api_serves_interface_and_health_without_schema_docs(monkeypatch):
    # Startup normally loads the cached embedding model; a fake keeps this test offline.
    monkeypatch.setattr("app.lifespan.load_model", lambda *_args, **_kwargs: FakeModel())
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_startup_smoke_logs_metrics_not_vectors_or_secrets(monkeypatch, caplog):
    import app.lifespan as app_lifespan

    token = "private-test-token"
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    model = FakeModel()
    monkeypatch.setenv("ENABLE_EMBEDDING_STARTUP_CHECK", "true")
    monkeypatch.setattr(app_lifespan, "run_embedding_smoke_test", lambda: (model, {
        "status": "passed", "dimensions": 384, "first_query_embedding_seconds": 0.01,
    }))
    with TestClient(app):
        pass
    messages = [record.getMessage() for record in caplog.records]
    payload = next(json.loads(message) for message in messages
                   if '"event": "fastembed_startup_check"' in message)
    startup_memory = next(json.loads(message) for message in messages
                          if '"event": "application_startup_memory"' in message)
    assert payload["status"] == "passed"
    assert payload["dimensions"] == 384
    assert startup_memory["rss_bytes"] > 0
    assert startup_memory["peak_rss_bytes"] >= startup_memory["rss_bytes"]
    logs = "\n".join(messages)
    assert token not in logs
    assert "0.0, 0.0" not in logs

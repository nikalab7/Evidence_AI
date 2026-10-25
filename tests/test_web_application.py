from contextlib import contextmanager
import json

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.llm.schemas import FunctionCall, LLMResponse
from app.main import app
from app.rate_limit import InvestigationLimiter


def metric(seconds=0.01):
    return [{"attempt": 1, "latency_seconds": seconds, "http_status": 200, "usage": {}}]


class FakeConnection:
    def __init__(self):
        self.in_transaction = False

    @contextmanager
    def transaction(self):
        self.in_transaction = True
        try:
            yield
        finally:
            self.in_transaction = False

    def execute(self, *_args):
        return None

    def close(self):
        return None


class ScriptedGemini:
    def __init__(self, responses):
        self.settings = type("ModelSettings", (), {"gemini_model": "gemini-3.5-flash-lite"})()
        self.responses = iter(responses)
        self.calls = []

    def generate(self, messages, *, tools=None, schema=None, request_budget=1, deadline=None):
        connection = getattr(self, "connection", None)
        if connection is not None:
            assert connection.in_transaction is False
        self.calls.append({"tools": tools, "schema": schema, "budget": request_budget, "deadline": deadline})
        return next(self.responses)


@pytest.fixture
def web_client():
    names = ("settings", "embedding_model", "gemini_client", "investigation_limiter", "memory_monitor")
    old = {name: getattr(app.state, name, None) for name in names}
    app.state.settings = Settings(
        "test-key", "gemini-3.5-flash-lite",
        "postgresql://user:pass@db.nldnpqhqrfwjgxcqeuru.supabase.co/postgres", "test-admin",
        investigation_daily_budget=10, investigation_per_ip_per_minute=20,
        investigation_max_concurrent=2,
    )
    app.state.embedding_model = object()
    app.state.gemini_client = object()
    app.state.investigation_limiter = InvestigationLimiter(
        daily_budget=10, per_ip_per_minute=20, max_concurrent=2,
    )
    app.state.memory_monitor = None
    try:
        yield TestClient(app)
    finally:
        for name, value in old.items():
            if value is None:
                try:
                    delattr(app.state, name)
                except AttributeError:
                    pass
            else:
                setattr(app.state, name, value)


def _hit():
    text = "A routing change delayed payment processing by 12 minutes."
    return {
        "chunk_id": "chunk-1", "doc_id": "doc-1", "title": "Incident report",
        "titles": ["Incident report"],
        "sources": [{"source_id": "source-1", "title_alias": "Incident report",
                     "source_url": "https://example.test/incident"},
                    {"source_id": "source-2", "title_alias": "Injected link",
                     "source_url": "javascript:alert(1)"},
                    {"source_id": "source-3", "title_alias": "Malformed URL",
                     "source_url": "https://[invalid"}],
        "evidence_text": text,
        "validation_source": {"full_text": text, "start_char": 0, "end_char": len(text)},
        "score": 0.8,
    }


def test_page_and_health_show_corpus_and_cold_start_notice(web_client):
    page = web_client.get("/")
    assert page.status_code == 200
    assert "50,000 indexed records" in page.text
    assert "This demo runs on free hosting. The first visit after inactivity may take approximately one minute to load." in page.text
    assert 'value="semantic" selected' in page.text
    assert 'id="loading"' in page.text
    assert 'id="insufficient"' in page.text and 'id="conflicts"' in page.text
    assert "textContent" in page.text and "innerHTML" not in page.text
    assert web_client.get("/health").json() == {"status": "ok"}


def test_http_investigation_runs_agent_and_returns_verified_citation(web_client, monkeypatch):
    import app.llm.service as service
    import app.llm.tools as tools

    conn = FakeConnection()
    monkeypatch.setattr(service, "connect_database", lambda: conn)
    monkeypatch.setattr(service, "load_model", lambda *_args, **_kwargs: pytest.fail("startup model must be reused"))
    modes = []
    monkeypatch.setattr(tools, "search", lambda _conn, _query, **kwargs: modes.append(kwargs["mode"]) or [_hit()])
    draft = {
        "central_claim_id": "claim-1",
        "claims": [{"claim_id": "claim-1", "text": "A routing change delayed payment processing.",
                    "citations": [{"chunk_id": "chunk-1", "quote": _hit()["evidence_text"]}]}],
        "conflict_groups": [],
    }
    client = ScriptedGemini([
        LLMResponse(None, [FunctionCall("search_evidence", {"query": "payment routing delay"}, "call-1"),],
                    {"parts": [{"functionCall": {"name": "search_evidence"}}]}, metric(), {}),
        LLMResponse("Evidence found.", [], {"parts": [{"text": "Evidence found."}]}, metric(), {}),
        LLMResponse(json.dumps(draft), [], {"parts": [{"text": "structured"}]}, metric(), {}),
    ])
    client.connection = conn
    web_client.app.state.gemini_client = client

    response = web_client.post("/api/investigate", json={"question": "Why was payment delayed?"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "answered"
    citation = body["claims"][0]["citations"][0]
    assert citation["chunk_id"] == "chunk-1"
    assert citation["quote"] == _hit()["evidence_text"]
    assert citation["sources"][0]["url"] == "https://example.test/incident"
    assert all(source.get("url") != "javascript:alert(1)" for source in citation["sources"])
    assert "trace" not in body and "api_usage" not in body
    assert modes == ["semantic"]
    assert len(client.calls) == 3


def test_http_investigation_abstains_when_no_evidence_is_returned(web_client, monkeypatch):
    import app.llm.service as service
    import app.llm.tools as tools

    conn = FakeConnection()
    monkeypatch.setattr(service, "connect_database", lambda: conn)
    monkeypatch.setattr(tools, "search", lambda *_args, **_kwargs: [])
    client = ScriptedGemini([
        LLMResponse("I will check the evidence.", [], {"parts": [{"text": "check"}]}, metric(), {}),
        LLMResponse(json.dumps({"central_claim_id": "", "claims": [], "conflict_groups": []}),
                    [], {"parts": [{"text": "structured"}]}, metric(), {}),
    ])
    client.connection = conn
    web_client.app.state.gemini_client = client

    response = web_client.post("/api/investigate", json={"question": "What evidence exists?"})

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient"
    assert response.json()["claims"] == []
    assert response.json()["answer"]


@pytest.mark.parametrize("payload", [
    {"question": "ab"},
    {"question": "valid question", "extra": "forbidden"},
    {"question": "valid question", "retrieval_mode": "unknown"},
    {"question": "valid\u0000 question"},
])
def test_request_validation_is_strict_and_sanitized(web_client, payload):
    response = web_client.post("/api/investigate", json=payload)
    assert response.status_code == 422
    assert "errors" not in response.text


def test_oversized_request_is_rejected_before_json_validation(web_client):
    response = web_client.post("/api/investigate", content=b" " * 17_000,
                               headers={"content-type": "application/json"})
    assert response.status_code == 413
    assert "too large" in response.json()["detail"]

    streamed = web_client.post(
        "/api/investigate",
        content=iter([b'{"question":"valid question"', b" " * 17_000, b"}"]),
        headers={"content-type": "application/json"},
    )
    assert streamed.status_code == 413


def test_daily_limit_returns_public_429_message(web_client, monkeypatch):
    import app.api.investigations as api

    web_client.app.state.investigation_limiter = InvestigationLimiter(
        daily_budget=1, per_ip_per_minute=20, max_concurrent=2,
    )
    monkeypatch.setattr(api, "run_investigation", lambda *_args, **_kwargs: {
        "status": "insufficient", "answer": "Not enough evidence.", "claims": [],
        "conflict_groups": [], "trace": {},
    })
    first = web_client.post("/api/investigate", json={"question": "First question"})
    second = web_client.post("/api/investigate", json={"question": "Second question"})
    assert first.status_code == 200
    assert second.status_code == 429
    assert "limit" in second.json()["detail"]
    assert "Retry-After" in second.headers


def test_keyword_and_hybrid_modes_remain_explicitly_available(web_client, monkeypatch):
    import app.api.investigations as api

    modes = []
    monkeypatch.setattr(api, "run_investigation", lambda _question, **kwargs: (
        modes.append(kwargs["retrieval_mode"]) or {
            "status": "insufficient", "answer": "Not enough evidence.", "claims": [],
            "conflict_groups": [], "trace": {},
        }
    ))
    for mode in ("keyword", "hybrid"):
        response = web_client.post("/api/investigate", json={
            "question": "Try this retrieval mode", "retrieval_mode": mode,
        })
        assert response.status_code == 200
    assert modes == ["keyword", "hybrid"]


def test_upstream_error_and_timeout_are_sanitized(web_client, monkeypatch):
    import app.api.investigations as api
    from app.llm.agent import InvestigationTimeout

    monkeypatch.setattr(api, "run_investigation", lambda *_args, **_kwargs: {
        "status": "insufficient", "answer": "Not enough evidence.", "claims": [],
        "conflict_groups": [], "trace": {"generation_error": "upstream_http_error: private"},
    })
    failure = web_client.post("/api/investigate", json={"question": "Could upstream fail?"})
    assert failure.status_code == 502
    assert "private" not in failure.text

    def timeout(*_args, **_kwargs):
        raise InvestigationTimeout()

    monkeypatch.setattr(api, "run_investigation", timeout)
    timed_out = web_client.post("/api/investigate", json={"question": "Will timeout happen?"})
    assert timed_out.status_code == 504
    assert "timed out" in timed_out.json()["detail"]

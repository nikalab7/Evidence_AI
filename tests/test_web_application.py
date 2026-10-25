from contextlib import contextmanager
import json
from time import perf_counter

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.llm.schemas import FunctionCall, InvestigationResult, LLMResponse
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
    for dom_id in (
        "investigation-form", "question-label", "question", "retrieval-mode",
        "submit-button", "loading", "error", "result", "result-status",
        "insufficient", "conflicts", "answer", "claims",
    ):
        assert f'id="{dom_id}"' in page.text
    assert "50,000 indexed records" in page.text
    assert "This demo runs on free hosting. The first visit after inactivity may take approximately one minute to load." in page.text
    assert 'value="semantic" selected' in page.text
    assert 'id="loading"' in page.text
    assert 'id="insufficient"' in page.text and 'id="conflicts"' in page.text
    assert "textContent" in page.text and "innerHTML" not in page.text
    assert "Verified citation" in page.text
    assert 'aria-labelledby="result-heading" tabindex="-1"' in page.text
    assert "firstCitationPending" in page.text and "details.open = firstCitationPending" in page.text
    assert "Evidence supporting statement" in page.text and "Passage ID:" in page.text
    assert 'meta.lastChild.append(element("code", "", citation.chunk_id))' in page.text
    assert 'question: askedText' in page.text and 'question: question.value' not in page.text
    assert 'details.append(element("blockquote", "", typeof citation.quote === "string" ? citation.quote : ""))' in page.text
    assert 'class="example-intent">Insufficient evidence example' in page.text
    assert "example.dataset.question" in page.text and "resizeQuestion" in page.text
    assert 'prefers-reduced-motion: reduce' in page.text
    assert "question.addEventListener(\"keydown\"" in page.text
    assert "animation: float .55s" in page.text
    assert "infinite alternate" not in page.text
    assert "result.focus({preventScroll: true})" in page.text
    assert web_client.get("/health").json() == {"status": "ok"}


def test_http_investigation_runs_agent_and_returns_verified_citation(web_client, monkeypatch, caplog):
    import app.llm.service as service
    import app.llm.tools as tools

    caplog.set_level("INFO", logger="uvicorn.error")
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
    assert body["conflict_groups"] == []
    assert modes == ["semantic"]
    assert len(client.calls) == 3
    assert "investigation_diagnostic" in caplog.text
    assert "query_matches_user_question" in caplog.text
    assert "Why was payment delayed?" not in caplog.text
    assert "A change delayed payment processing" not in caplog.text
    assert "Incident Report" not in caplog.text


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
    assert response.json()["conflict_groups"] == []
    assert response.json()["answer"]


def test_conflict_groups_are_public_and_trace_remains_private(web_client, monkeypatch):
    import app.api.investigations as api
    from app.llm.agent_support import finish

    result = finish(
        {
            "status": "conflicting",
            "answer": "The retrieved sources conflict. One says enabled; another says disabled.",
            "claims": [
                {"claim_id": "claim-enabled", "text": "The feature is enabled.",
                 "citations": [{"chunk_id": "chunk-1", "quote": "Feature: enabled."}]},
                {"claim_id": "claim-disabled", "text": "The feature is disabled.",
                 "citations": [{"chunk_id": "chunk-2", "quote": "Feature: disabled."}]},
            ],
            "central_claim_id": "claim-enabled",
            "conflict_groups": [["claim-enabled", "claim-disabled"]],
            "dropped_claim_ids": [],
        },
        {"tool_calls": [{"internal_query": "private trace"}],
         "api_usage": {"internal": "private"}},
        perf_counter(), "gemini-3.5-flash-lite",
    )
    assert isinstance(result, InvestigationResult)
    assert result.conflict_groups == [["claim-enabled", "claim-disabled"]]
    assert "conflict_groups" not in result.trace
    result.conflict_groups.append(["claim-enabled", "not-a-verified-claim"])
    monkeypatch.setattr(api, "run_investigation", lambda *_args, **_kwargs: result)

    response = web_client.post("/api/investigate", json={"question": "Is the feature enabled?"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "conflicting"
    assert body["conflict_groups"] == [["claim-enabled", "claim-disabled"]]
    assert [claim["claim_id"] for claim in body["claims"]] == ["claim-enabled", "claim-disabled"]
    assert [claim["citations"][0]["chunk_id"] for claim in body["claims"]] == ["chunk-1", "chunk-2"]
    assert "trace" not in body and "api_usage" not in body
    assert "private trace" not in response.text and "internal" not in response.text


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


def test_per_ip_limit_cannot_be_bypassed_by_forged_x_forwarded_for(web_client, monkeypatch):
    import app.api.investigations as api

    web_client.app.state.investigation_limiter = InvestigationLimiter(
        daily_budget=10, per_ip_per_minute=1, max_concurrent=2,
    )
    monkeypatch.setattr(api, "run_investigation", lambda *_args, **_kwargs: {
        "status": "insufficient", "answer": "Not enough evidence.", "claims": [],
        "conflict_groups": [], "trace": {},
    })
    edge_headers = {"CF-Connecting-IP": "203.0.113.21"}
    first = web_client.post("/api/investigate", json={"question": "First forwarded request"},
                            headers={**edge_headers, "X-Forwarded-For": "198.51.100.10"})
    second = web_client.post("/api/investigate", json={"question": "Second forwarded request"},
                             headers={**edge_headers, "X-Forwarded-For": "198.51.100.11"})
    assert first.status_code == 200
    assert second.status_code == 429
    assert "Too many investigations" in second.json()["detail"]


def test_client_ip_uses_single_cloudflare_header_or_socket_fallback():
    from starlette.requests import Request
    from app.api.investigations import _client_ip

    def make_request(headers, peer):
        return Request({
            "type": "http", "method": "POST", "path": "/api/investigate",
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers],
            "client": (peer, 44_321), "server": ("127.0.0.1", 8000),
            "scheme": "http", "query_string": b"",
        })

    proxied = make_request([
        ("cf-connecting-ip", "203.0.113.21"),
        ("x-forwarded-for", "198.51.100.10, 198.51.100.11"),
    ], "10.0.0.8")
    forged_only = make_request([
        ("x-forwarded-for", "198.51.100.99"),
    ], "10.0.0.9")
    duplicate_edge_headers = make_request([
        ("cf-connecting-ip", "203.0.113.21"),
        ("cf-connecting-ip", "203.0.113.22"),
        ("x-forwarded-for", "198.51.100.99"),
    ], "10.0.0.10")
    malformed_edge_header = make_request([
        ("cf-connecting-ip", "203.0.113.999"),
        ("x-forwarded-for", "198.51.100.99"),
    ], "10.0.0.11")

    assert _client_ip(proxied) == "203.0.113.21"
    assert _client_ip(forged_only) == "10.0.0.9"
    assert _client_ip(duplicate_edge_headers) == "10.0.0.10"
    assert _client_ip(malformed_edge_header) == "10.0.0.11"


def test_frankfurt_start_command_disables_uvicorn_proxy_header_trust():
    from pathlib import Path

    blueprint = Path(__file__).resolve().parents[1] / "render.frankfurt.yaml"
    start_command = next(
        line for line in blueprint.read_text(encoding="utf-8").splitlines()
        if "startCommand:" in line
    )
    assert "--no-proxy-headers" in start_command
    assert " --forwarded-allow-ips=" not in start_command
    assert " --proxy-headers " not in start_command


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

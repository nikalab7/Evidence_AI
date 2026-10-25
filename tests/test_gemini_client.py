import json

import httpx
import pytest

from app.config import Settings
from app.llm.gemini_client import GeminiAPIError, GeminiClient


def test_function_call_request_uses_configured_model_and_header_secret():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["x-goog-api-key"] == "api-secret"
        assert "api-secret" not in str(request.url)
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"functionCall": {
                "name": "search_evidence", "args": {"query": "payment latency"}, "id": "call-1",
            }}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2},
        })

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http:
        client = GeminiClient(Settings(gemini_api_key="api-secret", gemini_model="gemini-3.5-flash-lite"), client=http)
        result = client.generate([
            {"role": "system", "parts": [{"text": "system instruction"}]},
            {"role": "user", "parts": [{"text": "search"}]},
        ], tools=[{"name": "search_evidence"}])
    assert len(requests) == 1
    assert requests[0].url.path.endswith("/models/gemini-3.5-flash-lite:generateContent")
    body = requests[0].read().decode()
    assert "systemInstruction" in body and "search_evidence" in body
    assert json.loads(body)["generationConfig"]["maxOutputTokens"] == 1024
    assert result.function_calls[0].call_id == "call-1"
    assert result.usage["promptTokenCount"] == 10
    assert result.usage["candidatesTokenCount"] == 2
    assert result.request_metrics[0]["http_status"] == 200


def test_retries_transient_http_error_within_explicit_request_budget(monkeypatch):
    attempts = []

    def handler(_request):
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(503, json={"error": "private upstream detail"})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "OK"}]}}]})

    monkeypatch.setattr("app.llm.gemini_client.time.sleep", lambda *_args: None)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = GeminiClient(Settings(gemini_api_key="key", gemini_model="flash-lite"), client=http)
        result = client.generate([{"role": "user", "parts": [{"text": "hello"}]}], request_budget=2)
    assert len(attempts) == 2
    assert result.request_metrics[0]["http_status"] == 503
    assert result.request_metrics[1]["http_status"] == 200


def test_request_budget_one_prevents_retry_and_errors_are_sanitized(monkeypatch):
    calls = []

    def handler(_request):
        calls.append(1)
        return httpx.Response(500, json={"error": "key=private-value"})

    monkeypatch.setattr("app.llm.gemini_client.time.sleep", lambda *_args: None)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = GeminiClient(Settings(gemini_api_key="secret"), client=http)
        with pytest.raises(GeminiAPIError) as error:
            client.generate([{"role": "user", "parts": [{"text": "hello"}]}], request_budget=1)
    assert len(calls) == 1
    assert error.value.reason == "upstream_http_error"
    assert "private-value" not in str(error.value)
    assert len(error.value.request_metrics) == 1


@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "private quota detail"}}),
        (403, {"error": {"code": 403, "status": "RESOURCE_EXHAUSTED", "message": "private quota detail"}}),
    ],
)
def test_evaluation_rate_limit_mode_stops_without_retry_or_body_leak(status, payload):
    calls = []

    def handler(_request):
        calls.append(1)
        return httpx.Response(status, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = GeminiClient(
            Settings(gemini_api_key="key"), client=http, stop_on_rate_limit=True,
        )
        with pytest.raises(GeminiAPIError) as error:
            client.generate([{"role": "user", "parts": [{"text": "hello"}]}], request_budget=5)

    assert len(calls) == 1
    assert error.value.reason == "provider_quota_exhausted"
    assert error.value.status == status
    assert len(error.value.request_metrics) == 1
    assert "private quota detail" not in str(error.value)


def test_structured_output_schema_is_sent_as_json_configuration():
    bodies = []

    def handler(request):
        bodies.append(request.read().decode())
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = GeminiClient(Settings(gemini_api_key="key"), client=http)
        client.generate([{"role": "user", "parts": [{"text": "json"}]}], schema={"type": "OBJECT"})
    assert '"responseMimeType":"application/json"' in bodies[0]
    assert '"responseSchema":{"type":"OBJECT"}' in bodies[0]

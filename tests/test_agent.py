import json

from app.llm.agent import investigate
from app.llm.schemas import FunctionCall, LLMResponse


def _metric(n):
    return [{"attempt": 1, "latency_seconds": n, "http_status": 200, "usage": {"totalTokenCount": 3}}]


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.settings = type("Settings", (), {"gemini_model": "gemini-3.5-flash-lite"})()

    def generate(self, messages, *, tools=None, schema=None, request_budget=1):
        self.calls.append({"tools": tools, "schema": schema, "budget": request_budget})
        return next(self.responses)


def _search_hit():
    text = "A change delayed payment processing by 12 minutes."
    return {"chunk_id": "chunk-1", "doc_id": "doc-1", "title": "Incident Report",
            "titles": ["Incident Report"], "sources": [{"source_id": "src-1", "title_alias": "Incident Report"}],
            "evidence_text": text, "validation_source": {"full_text": text, "start_char": 0, "end_char": len(text)},
            "score": 0.8}


def test_search_tool_answer_is_citation_checked_and_latency_is_reported(monkeypatch):
    import app.llm.tools as tools

    monkeypatch.setattr(tools, "search", lambda *_args, **_kwargs: [_search_hit()])
    draft = {"central_claim_id": "c1", "claims": [{"claim_id": "c1",
        "text": "A change delayed payment processing.", "citations": [{"chunk_id": "chunk-1",
        "quote": "A change delayed payment processing by 12 minutes."}]}], "conflict_groups": []}
    llm = ScriptedLLM([
        LLMResponse(None, [FunctionCall("search_evidence", {"query": "payment processing delay"}, "fc1")],
                    {"parts": [{"functionCall": {"name": "search_evidence"}}]}, _metric(0.12), {"totalTokenCount": 3}),
        LLMResponse("I found relevant evidence.", [], {"parts": [{"text": "I found relevant evidence."}]},
                    _metric(0.05), {"totalTokenCount": 2}),
        LLMResponse(json.dumps(draft), [], {"parts": [{"text": "structured"}]}, _metric(0.2), {"totalTokenCount": 4}),
    ])
    result = investigate("Why was payment processing delayed?", conn=object(), embedding_model=object(), llm_client=llm)
    assert result.status == "answered"
    assert result.claims[0]["citations"][0]["sources"][0]["source_id"] == "src-1"
    assert result.trace["tool_calls"][0]["tool"] == "search_evidence"
    assert result.trace["api_usage"]["request_count"] == 3
    assert result.trace["api_usage"]["tokens"]["totalTokenCount"] == 9


def test_agent_stops_at_four_tool_steps_and_five_http_requests(monkeypatch):
    import app.llm.tools as tools

    monkeypatch.setattr(tools, "search", lambda *_args, **_kwargs: [])
    responses = [
        LLMResponse(None, [FunctionCall("search_evidence", {"query": f"query {n}"})],
                    {"parts": [{"functionCall": {"name": "search_evidence"}}]}, _metric(0.01), {})
        for n in range(4)
    ]
    responses.append(LLMResponse(json.dumps({"central_claim_id": "", "claims": [], "conflict_groups": []}),
                                 [], {"parts": [{"text": "{}"}]}, _metric(0.01), {}))
    llm = ScriptedLLM(responses)
    result = investigate("A multi-hop question", conn=object(), embedding_model=object(), llm_client=llm)
    assert result.status == "insufficient"
    assert result.trace["investigation_steps"] == 4
    assert result.trace["api_usage"]["request_count"] == 5
    assert len(result.trace["tool_calls"]) == 4
    assert [call["budget"] for call in llm.calls[:4]] == [4, 3, 2, 1]
    assert llm.calls[4]["schema"] is not None

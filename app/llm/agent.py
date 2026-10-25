"""Bounded Gemini tool loop with post-generation citation verification."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from collections.abc import Mapping
from typing import Any, Literal

from app.config import DEFAULT_GEMINI_MODEL
from app.llm.agent_support import SYSTEM_PROMPT, add_usage, finish, record_requests, trace_arguments
from app.llm.gemini_client import GeminiAPIError
from app.llm.schemas import (
    FINAL_RESPONSE_SCHEMA, MAX_INVESTIGATION_STEPS, MAX_LLM_REQUESTS,
    InvestigationResult,
)
from app.llm.tools import TOOL_DECLARATIONS, execute_tool
from app.reasoning.citations import validate_final_response


RetrievalMode = Literal["semantic", "keyword", "hybrid"]


class InvestigationTimeout(TimeoutError):
    """Raised when an investigation reaches its configured wall-clock deadline."""


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.perf_counter() >= deadline:
        raise InvestigationTimeout("investigation timed out")


def _close_read_transaction(conn: Any) -> None:
    if getattr(conn, "in_transaction", False):
        conn.rollback()


def investigate(
    question: str, *, conn: Any, embedding_model: Any, llm_client: Any,
    filters: dict[str, str] | None = None,
    retrieval_mode: RetrievalMode = "semantic",
    database_statement_timeout_ms: int = 12_000,
    deadline: float | None = None,
    started_at: float | None = None,
    database_connection_seconds: float = 0.0,
    model_initialization_seconds: float = 0.0,
    capture_evaluation_details: bool = False,
    search_function: Callable[..., list[dict[str, Any]]] | None = None,
) -> InvestigationResult:
    """Run up to four retrieval tools and five actual Gemini HTTP requests."""
    started = started_at if started_at is not None else time.perf_counter()
    trace: dict[str, Any] = {
        "database_connection_seconds": round(database_connection_seconds, 6),
        "model_initialization_seconds": round(model_initialization_seconds, 6),
        "tool_calls": [], "llm_requests": [], "api_usage": {},
    }
    if not isinstance(question, str) or not question.strip():
        return finish(None, trace, started, DEFAULT_GEMINI_MODEL)

    messages: list[dict[str, Any]] = [
        {"role": "system", "parts": [{"text": SYSTEM_PROMPT}]},
        {"role": "user", "parts": [{"text": question.strip()}]},
    ]
    retrieved: dict[str, dict[str, Any]] = {}
    evaluation_retrieval_results: list[dict[str, Any]] = []
    api_calls, tool_calls = 0, 0
    usage: dict[str, int] = {}
    model_name = getattr(getattr(llm_client, "settings", None), "gemini_model", "") or DEFAULT_GEMINI_MODEL
    generation_error = None

    while tool_calls < MAX_INVESTIGATION_STEPS and api_calls < MAX_LLM_REQUESTS - 1:
        budget = MAX_LLM_REQUESTS - api_calls - 1  # reserve one request for structured final output
        try:
            _check_deadline(deadline)
            _close_read_transaction(conn)
            response = llm_client.generate(
                messages, tools=TOOL_DECLARATIONS, request_budget=budget,
                deadline=deadline,
            )
        except GeminiAPIError as exc:
            api_calls = record_requests(trace, api_calls, exc.request_metrics)
            if exc.reason == "investigation_timeout" or (
                deadline is not None and time.perf_counter() >= deadline
            ):
                raise InvestigationTimeout("investigation timed out") from None
            generation_error = exc.reason
            break
        _check_deadline(deadline)
        api_calls = record_requests(trace, api_calls, response.request_metrics)
        add_usage(usage, response.usage)
        messages.append({"role": "model", "parts": response.model_content.get("parts", [])})
        if not response.function_calls:
            break
        for function in response.function_calls:
            if tool_calls >= MAX_INVESTIGATION_STEPS:
                response_part = {"name": function.name, "response": {"error": "step_budget_exhausted"}}
                if function.call_id:
                    response_part["id"] = function.call_id
                messages.append({"role": "user", "parts": [{"functionResponse": response_part}]})
                trace["tool_budget_rejections"] = trace.get("tool_budget_rejections", 0) + 1
                continue
            safe_args = function.arguments if isinstance(function.arguments, dict) else {}
            tool_started = time.perf_counter()
            try:
                _check_deadline(deadline)
                result, timing = execute_tool(
                    conn, embedding_model, function.name, safe_args,
                    retrieved=retrieved, filters=filters,
                    retrieval_mode=retrieval_mode,
                    original_question=question,
                    database_statement_timeout_ms=database_statement_timeout_ms,
                    evaluation_retrieval_results=(
                        evaluation_retrieval_results if capture_evaluation_details else None
                    ),
                    search_function=search_function,
                )
                outcome = "error" if "error" in result else "ok"
            except InvestigationTimeout:
                raise
            except Exception as exc:
                result, outcome = {"error": "tool_execution_failed"}, "error"
                timing = {"tool": function.name,
                          "total_seconds": round(time.perf_counter() - tool_started, 6),
                          "error_type": type(exc).__name__}
            tool_calls += 1
            if function.name == "search_evidence" and capture_evaluation_details:
                for item in evaluation_retrieval_results:
                    if "tool_call_index" not in item:
                        item["tool_call_index"] = tool_calls
            timing.update({"step": tool_calls, "outcome": outcome})
            timing["arguments"] = trace_arguments(
                function.name, safe_args, original_question=question,
            )
            if function.name == "search_evidence":
                hits = result.get("results", []) if isinstance(result, dict) else []
                timing.setdefault("retrieved_chunk_count", len(hits))
            elif function.name == "get_document" and isinstance(result, dict):
                timing["document_characters"] = len(result.get("full_text", ""))
            trace["tool_calls"].append(timing)
            function_response: dict[str, Any] = {"name": function.name, "response": result}
            if function.call_id:
                function_response["id"] = function.call_id
            messages.append({"role": "user", "parts": [{"functionResponse": function_response}]})

    final_draft: Mapping[str, Any] | None = None
    if generation_error is None and api_calls < MAX_LLM_REQUESTS:
        messages.append({"role": "user", "parts": [{"text": (
            "Return the final structured claims now. Use only the retrieved evidence "
            "above. Put every factual statement in a separately cited claim. Set "
            "central_claim_id to the main claim, or use an empty string when the "
            "evidence is insufficient. Include conflict_groups only for incompatible "
            "verified claims."
        )}]})
        while api_calls < MAX_LLM_REQUESTS:
            try:
                _check_deadline(deadline)
                _close_read_transaction(conn)
                response = llm_client.generate(
                    messages, schema=FINAL_RESPONSE_SCHEMA,
                    request_budget=MAX_LLM_REQUESTS - api_calls,
                    deadline=deadline,
                )
            except GeminiAPIError as exc:
                api_calls = record_requests(trace, api_calls, exc.request_metrics)
                if exc.reason == "investigation_timeout" or (
                    deadline is not None and time.perf_counter() >= deadline
                ):
                    raise InvestigationTimeout("investigation timed out") from None
                generation_error = exc.reason
                break
            _check_deadline(deadline)
            api_calls = record_requests(trace, api_calls, response.request_metrics)
            add_usage(usage, response.usage)
            try:
                decoded = json.loads(response.text or "")
                if isinstance(decoded, Mapping):
                    final_draft = decoded
                    break
            except (json.JSONDecodeError, TypeError):
                pass
            messages.append({"role": "model", "parts": [{"text": response.text or ""}]})
            messages.append({"role": "user", "parts": [{"text": "Return valid JSON matching the requested schema."}]})

    trace["api_usage"] = {
        "model": model_name, "request_count": api_calls, "tokens": usage,
        "request_latencies_seconds": [item["latency_seconds"] for item in trace["llm_requests"]],
        "latency_seconds": round(sum(item["latency_seconds"] for item in trace["llm_requests"]), 6),
    }
    trace["investigation_steps"] = tool_calls
    trace["generation_error"] = generation_error
    verified = validate_final_response(final_draft or {}, retrieved)
    trace["validated_citations"] = sum(len(claim["citations"]) for claim in verified["claims"])
    trace["verified_claims"] = len(verified["claims"])
    trace["dropped_claims"] = len(verified["dropped_claim_ids"])
    draft_claims = final_draft.get("claims") if isinstance(final_draft, Mapping) else None
    claim_items = draft_claims if isinstance(draft_claims, list) else []
    if generation_error is not None:
        diagnostic = "generation_failed"
    elif not retrieved:
        diagnostic = "evidence_not_retrieved"
    elif final_draft is None:
        diagnostic = "final_response_unavailable"
    elif not claim_items:
        if (final_draft.get("claims") == []
                and final_draft.get("central_claim_id") in ("", None)):
            diagnostic = "model_abstained"
        else:
            diagnostic = "invalid_final_response"
    elif not any(isinstance(item, Mapping) and item.get("citations") for item in claim_items):
        diagnostic = "evidence_retrieved_but_not_cited"
    elif verified["dropped_claim_ids"]:
        diagnostic = "citation_rejected"
    elif verified["central_claim_id"] not in {
        claim["claim_id"] for claim in verified["claims"]
    }:
        diagnostic = "central_claim_unverified"
    else:
        diagnostic = "citations_verified"
    trace["evidence_diagnostic"] = {
        "outcome": diagnostic,
        "retrieved_chunk_count": len(retrieved),
        "draft_claim_count": len(claim_items),
        "verified_claim_count": len(verified["claims"]),
        "rejected_claim_count": len(verified["dropped_claim_ids"]),
        "draft_citation_count": sum(
            len(item.get("citations", []))
            for item in claim_items if isinstance(item, Mapping)
            and isinstance(item.get("citations"), list)
        ),
        "verified_citation_count": sum(len(claim["citations"]) for claim in verified["claims"]),
    }
    if capture_evaluation_details:
        trace["evaluation_retrieval_results"] = evaluation_retrieval_results
    return finish(verified, trace, started, model_name)

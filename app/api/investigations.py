"""Public investigation API with strict input and sanitized responses."""

from __future__ import annotations

import json
from logging import getLogger
from time import perf_counter
from typing import Any, Literal
import unicodedata
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import Settings
from app.llm.agent import InvestigationTimeout
from app.llm.service import run_investigation
from app.memory_monitor import ProcessMemoryMonitor, RequestMemorySample
from app.rate_limit import InvestigationLimiter, LimitRejection


logger = getLogger("uvicorn.error")
router = APIRouter(prefix="/api", tags=["investigations"])
RetrievalMode = Literal["semantic", "keyword", "hybrid"]


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(strict=True, min_length=3, max_length=1_000)
    retrieval_mode: RetrievalMode = "semantic"

    @field_validator("question", mode="before")
    @classmethod
    def normalize_and_validate_question(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("question must be text")
        normalized = " ".join(value.split())
        if not 3 <= len(normalized) <= 1_000:
            raise ValueError("question must contain between 3 and 1000 characters")
        if any(unicodedata.category(char).startswith("C") for char in normalized):
            raise ValueError("question contains unsupported control characters")
        return normalized


def _client_ip(request: Request) -> str:
    client = request.client
    if client is None or not client.host:
        return "unknown"
    return client.host


def _limit_response(rejection: LimitRejection) -> HTTPException:
    if rejection.reason == "disabled":
        return HTTPException(
            status_code=503,
            detail="Investigations are temporarily unavailable while service limits are configured.",
        )
    messages = {
        "per_ip": "Too many investigations from this network. Please try again shortly.",
        "daily": "The demo has reached today's investigation limit. Please try again tomorrow.",
        "concurrent": "EvidenceAI is busy with other questions. Please try again shortly.",
    }
    return HTTPException(
        status_code=429,
        detail=messages.get(rejection.reason, "Investigation request limit reached."),
        headers={"Retry-After": str(max(1, rejection.retry_after_seconds))},
    )


def _safe_public_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        return None
    return value


def _public_result(raw: Any) -> dict[str, Any]:
    data = raw.as_dict() if hasattr(raw, "as_dict") else raw
    if not isinstance(data, dict) or data.get("status") not in {"answered", "insufficient", "conflicting"}:
        raise ValueError("invalid investigation result")
    claims = []
    for claim in data.get("claims", []):
        if not isinstance(claim, dict):
            continue
        citations = []
        for citation in claim.get("citations", []):
            if not isinstance(citation, dict):
                continue
            sources = []
            for source in citation.get("sources", []):
                if not isinstance(source, dict):
                    continue
                title = source.get("title_alias")
                url = _safe_public_url(source.get("source_url"))
                item = {"title": title} if isinstance(title, str) and title else {}
                if url:
                    item["url"] = url
                if item:
                    sources.append(item)
            titles = citation.get("titles")
            if not isinstance(titles, list):
                titles = [citation.get("title")] if citation.get("title") else []
            citations.append({
                "chunk_id": citation.get("chunk_id"),
                "quote": citation.get("quote", ""),
                "titles": [title for title in titles if isinstance(title, str)],
                "sources": sources,
            })
        claims.append({
            "claim_id": claim.get("claim_id"),
            "text": claim.get("text", ""),
            "citations": citations,
        })
    conflict_groups = data.get("conflict_groups", [])
    safe_groups = [
        [item for item in group if isinstance(item, str)]
        for group in conflict_groups
        if isinstance(group, list)
    ]
    return {
        "status": data["status"],
        "answer": data.get("answer", ""),
        "claims": claims,
        "conflict_groups": safe_groups,
    }


def _get_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    return settings if isinstance(settings, Settings) else Settings.load()


def _get_limiter(request: Request, settings: Settings) -> InvestigationLimiter:
    limiter = getattr(request.app.state, "investigation_limiter", None)
    if limiter is None:
        limiter = InvestigationLimiter(
            daily_budget=settings.investigation_daily_budget,
            per_ip_per_minute=settings.investigation_per_ip_per_minute,
            max_concurrent=settings.investigation_max_concurrent,
        )
        request.app.state.investigation_limiter = limiter
    return limiter


@router.post("/investigate")
async def investigate_endpoint(
    payload: InvestigationRequest,
    request: Request,
) -> dict[str, Any]:
    settings = _get_settings(request)
    model = getattr(request.app.state, "embedding_model", None)
    llm_client = getattr(request.app.state, "gemini_client", None)
    if model is None or llm_client is None:
        raise HTTPException(
            status_code=503,
            detail="Investigation service is not ready. Please try again later.",
        )
    limiter = _get_limiter(request, settings)
    rejection = limiter.reserve(_client_ip(request))
    if rejection is not None:
        raise _limit_response(rejection)

    started = perf_counter()
    memory_sample: RequestMemorySample | None = None
    outcome = "error"
    try:
        monitor = getattr(request.app.state, "memory_monitor", None)
        if isinstance(monitor, ProcessMemoryMonitor):
            with monitor.track() as memory_sample:
                result = await run_in_threadpool(
                    run_investigation,
                    payload.question,
                    settings=settings,
                    model=model,
                    llm_client=llm_client,
                    retrieval_mode=payload.retrieval_mode,
                )
        else:
            result = await run_in_threadpool(
                run_investigation,
                payload.question,
                settings=settings,
                model=model,
                llm_client=llm_client,
                retrieval_mode=payload.retrieval_mode,
            )
        trace = result.get("trace") if isinstance(result, dict) else getattr(result, "trace", None)
        if isinstance(trace, dict) and trace.get("generation_error"):
            if "timeout" in str(trace["generation_error"]):
                raise HTTPException(status_code=504, detail="The investigation timed out. Please try again.")
            raise HTTPException(
                status_code=502,
                detail="The investigation service could not complete this request. Please try again.",
            )
        public_result = _public_result(result)
        outcome = public_result["status"]
        return public_result
    except InvestigationTimeout:
        raise HTTPException(status_code=504, detail="The investigation timed out. Please try again.") from None
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("investigation_request_failed error_type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="The investigation service is temporarily unavailable. Please try again.",
        ) from None
    finally:
        limiter.release()
        if memory_sample is not None:
            memory_data = memory_sample.as_dict()
            memory_limit = 512 * 1024 * 1024
            peak_rss = memory_data["peak_rss_bytes"]
            logger.info("investigation_memory %s", json.dumps({
                "event": "investigation_memory",
                **memory_data,
                "elapsed_seconds": round(perf_counter() - started, 4),
                "outcome": outcome,
                "render_free_memory_limit_bytes": memory_limit,
                "sampled_peak_below_limit": peak_rss is not None and peak_rss < memory_limit,
            }, sort_keys=True))

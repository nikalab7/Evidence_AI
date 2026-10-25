"""Minimal REST Gemini client with bounded, measurable request retries."""

from __future__ import annotations

import re
import time
from typing import Any, Mapping, Sequence

import httpx

from app.config import DEFAULT_GEMINI_MODEL, Settings
from app.llm.gemini_protocol import API_BASE, parse_response, request_body, request_metric, usage_counts
from app.llm.schemas import LLMResponse


_MODEL_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class GeminiAPIError(RuntimeError):
    """Sanitized upstream failure with request timing for budget accounting."""

    def __init__(self, reason: str, metrics: list[dict[str, Any]], status: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.request_metrics = metrics
        self.status = status


class GeminiClient:
    def __init__(
        self, settings: Settings, *, client: httpx.Client | None = None,
        timeout_seconds: float | None = None, max_retries: int = 1,
        stop_on_rate_limit: bool = False,
    ):
        self.settings = settings
        self.timeout_seconds = timeout_seconds or settings.gemini_request_timeout_seconds
        self.max_retries = max_retries
        self.stop_on_rate_limit = stop_on_rate_limit
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=self.timeout_seconds, follow_redirects=False)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "GeminiClient":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def generate(
        self, messages: Sequence[Mapping[str, Any]], *,
        tools: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
        request_budget: int = 1,
        deadline: float | None = None,
    ) -> LLMResponse:
        """Generate content; each HTTP attempt consumes one investigation call."""
        if not self.settings.gemini_api_key:
            raise GeminiAPIError("missing_api_key", [])
        if not 1 <= request_budget <= 5:
            raise ValueError("request_budget must be between one and five")
        model = (self.settings.gemini_model or DEFAULT_GEMINI_MODEL).removeprefix("models/")
        if not _MODEL_RE.fullmatch(model):
            raise GeminiAPIError("invalid_model_name", [])
        body = request_body(
            messages, tools, schema,
            max_output_tokens=self.settings.gemini_max_output_tokens,
        )
        metrics: list[dict[str, Any]] = []
        max_attempts = min(self.max_retries + 1, request_budget)
        for attempt in range(1, max_attempts + 1):
            timeout_seconds = self.timeout_seconds
            if deadline is not None:
                remaining_seconds = deadline - time.perf_counter()
                if remaining_seconds <= 0:
                    raise GeminiAPIError("investigation_timeout", metrics) from None
                timeout_seconds = min(timeout_seconds, remaining_seconds)
            started = time.perf_counter()
            status = None
            try:
                response = self.client.post(
                    f"{API_BASE}/models/{model}:generateContent",
                    headers={"x-goog-api-key": self.settings.gemini_api_key}, json=body,
                    timeout=timeout_seconds,
                )
                status = response.status_code
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                quota_exhausted = status == 429 or _is_quota_exhaustion(exc.response)
                retryable = (status >= 500 or (status == 429 and not self.stop_on_rate_limit))
                if self.stop_on_rate_limit and quota_exhausted:
                    retryable = False
                reason = "provider_quota_exhausted" if quota_exhausted else "upstream_http_error"
            except httpx.TimeoutException:
                retryable, reason = True, "upstream_timeout"
            except httpx.RequestError:
                retryable, reason = True, "upstream_network_error"
            except (ValueError, TypeError):
                retryable, reason = False, "invalid_upstream_response"
            else:
                elapsed = time.perf_counter() - started
                usage = usage_counts(payload.get("usageMetadata", {}) if isinstance(payload, Mapping) else {})
                metric = request_metric(attempt, elapsed, status, usage)
                try:
                    generated = parse_response(payload, [*metrics, metric], usage)
                except (ValueError, TypeError, KeyError, AttributeError):
                    metrics.append(metric)
                    raise GeminiAPIError("invalid_upstream_response", metrics, status) from None
                metrics.append(metric)
                return generated
            metrics.append(request_metric(attempt, time.perf_counter() - started, status, {}))
            if not retryable or attempt == max_attempts:
                raise GeminiAPIError(reason, metrics, status) from None
            backoff = min(0.1 * (2 ** (attempt - 1)), 0.3)
            if deadline is not None and time.perf_counter() + backoff >= deadline:
                raise GeminiAPIError("investigation_timeout", metrics, status) from None
            time.sleep(backoff)
        raise GeminiAPIError("request_budget_exhausted", metrics)


def _is_quota_exhaustion(response: httpx.Response) -> bool:
    """Recognize Google's quota error code without retaining or logging its body."""
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return False
    if not isinstance(payload, Mapping):
        return False
    error = payload.get("error")
    return (
        isinstance(error, Mapping)
        and (
            error.get("status") == "RESOURCE_EXHAUSTED"
            or error.get("code") == 429
        )
    )

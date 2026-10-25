"""Opt-in development comparison, sharing the existing rolling reservation ledger."""

import hashlib
import json
from time import perf_counter

from app.config import DEFAULT_GEMINI_MODEL, Settings
from app.db.connection import EXPECTED_SUPABASE_PROJECT_REF, connect_database, project_ref_from_database_url
from app.evaluation.final_runner import (
    DEFAULT_LEDGER, _acquire_ledger_lock, _all_reservations, _append_jsonl,
    _fixture_search, _read_output, _repair_incomplete_result_tail, build_run_key,
    check_indexed_coverage, make_case_result, require_complete_indexed_coverage,
    reserve_investigation,
)
from app.evaluation.quality_baseline import baseline_agent
from app.evaluation.quality_dev import ROOT, run_fingerprint, summarize
from app.llm.agent import investigate
from app.llm.gemini_client import GeminiAPIError, GeminiClient
from app.llm.schemas import MAX_LLM_REQUESTS
from app.model_cache import load_model


class TrackedClient:
    """Retain all HTTP attempt metrics even when a later call raises."""

    def __init__(self, client):
        self.client = client
        self.settings = client.settings
        self.stop_on_rate_limit = True
        self.metrics = []

    def generate(self, *args, **kwargs):
        remaining = MAX_LLM_REQUESTS - len(self.metrics)
        if remaining <= 0:
            raise GeminiAPIError("request_budget_exhausted", [])
        kwargs["request_budget"] = min(kwargs.get("request_budget", remaining), remaining)
        try:
            result = self.client.generate(*args, **kwargs)
        except Exception as exc:
            self.metrics.extend(getattr(exc, "request_metrics", []))
            raise
        self.metrics.extend(result.request_metrics)
        return result


def run_case(case, *, settings, model, agent, tracked):
    started = perf_counter()
    conn = None
    try:
        if case["execution_mode"] == "live":
            conn = connect_database(autocommit=True)
            conn.execute("SET default_transaction_read_only = on")
        connection_seconds = perf_counter() - started
        result = agent(
            case["question"], conn=conn if conn is not None else object(),
            embedding_model=model, llm_client=tracked, retrieval_mode="semantic",
            database_statement_timeout_ms=settings.database_statement_timeout_ms,
            deadline=started + settings.investigation_timeout_seconds,
            started_at=started, database_connection_seconds=connection_seconds,
            capture_evaluation_details=True,
            search_function=_fixture_search(case) if case["execution_mode"] == "fixture" else None,
        )
        return result.as_dict()
    finally:
        if conn is not None:
            conn.close()


def run_live_comparison(cases, *, variant, settings: Settings, max_investigations: int):
    if variant not in {"before", "after"} or not 1 <= max_investigations <= 30:
        raise ValueError("select before/after and a maximum of 1 through 30 investigations")
    if project_ref_from_database_url(settings.database_url) != EXPECTED_SUPABASE_PROJECT_REF:
        raise RuntimeError("development comparison requires the approved Frankfurt project")
    if not settings.gemini_api_key or settings.investigation_daily_budget <= 0:
        raise RuntimeError("live API key and a positive local budget are required")
    model_name = settings.gemini_model or DEFAULT_GEMINI_MODEL
    fingerprint = hashlib.sha256(json.dumps({
        "code_inputs": run_fingerprint(variant), "model": model_name,
        "output_tokens": settings.gemini_max_output_tokens,
        "timeout": settings.investigation_timeout_seconds,
        "request_timeout": settings.gemini_request_timeout_seconds,
    }, sort_keys=True).encode()).hexdigest()
    results_path = ROOT / f"reports/quality_dev_{variant}_results.jsonl"
    lock = DEFAULT_LEDGER.with_name(DEFAULT_LEDGER.name + ".lock")
    _acquire_ledger_lock(lock)
    completed_this_run = 0
    requests_this_run = 0
    stop_reason = None
    try:
        _repair_incomplete_result_tail(results_path)
        existing = _read_output(results_path, fingerprint, model_name)
        reservations = {r["run_key"] for r in _all_reservations(DEFAULT_LEDGER)}
        pending = [(c, build_run_key(c["case_id"], "semantic", fingerprint, model_name))
                   for c in cases]
        pending = [(c, key) for c, key in pending if key not in existing]
        if any(key in reservations for _, key in pending):
            raise RuntimeError("uncertain development reservation exists; automatic retry refused")
        live_cases = [c for c, _ in pending if c["execution_mode"] == "live"]
        if live_cases:
            require_complete_indexed_coverage(live_cases, check_indexed_coverage(live_cases))
        agent = baseline_agent() if variant == "before" else investigate
        model = load_model("BAAI/bge-small-en-v1.5", threads=1) if live_cases else None
        for case, key in pending[:max_investigations]:
            if not reserve_investigation(DEFAULT_LEDGER, run_key=key, case_id=case["case_id"],
                                         mode="semantic", daily_budget=settings.investigation_daily_budget):
                stop_reason = "local_rolling_budget_reached"
                break
            raw, error_type = None, None
            with GeminiClient(settings, stop_on_rate_limit=True) as client:
                tracked = TrackedClient(client)
                started = perf_counter()
                try:
                    raw = run_case(case, settings=settings, model=model, agent=agent, tracked=tracked)
                except Exception as exc:
                    error_type = type(exc).__name__
                    stop_reason = "provider_quota" if getattr(exc, "status", None) == 429 else "investigation_error"
                row = make_case_result(case, mode="semantic", raw_result=raw,
                                       dataset_sha256=fingerprint, model=model_name, error_type=error_type)
                row["api_request_count"] = len(tracked.metrics)
                row["latency_seconds"] = perf_counter() - started
                row["variant"] = variant
                row["predicted_conflict_groups"] = (raw or {}).get("conflict_groups", [])
                row["private_evaluation_details"] = (raw or {}).get("trace", {})
                _append_jsonl(results_path, row)
                existing[key] = row
                requests_this_run += len(tracked.metrics)
                completed_this_run += 1
            if stop_reason:
                break
        return {
            "variant": variant, "completed_this_run": completed_this_run,
            "requests_this_run": requests_this_run, "stop_reason": stop_reason,
            "run_fingerprint": fingerprint, "summary": summarize(list(existing.values()), cases),
        }
    finally:
        lock.unlink(missing_ok=True)

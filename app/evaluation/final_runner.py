"""Resumable, budget-gated answer evaluation over the fixed final case set."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
from time import perf_counter
from typing import Any

from app.config import DEFAULT_GEMINI_MODEL, Settings
from app.db.connection import EXPECTED_SUPABASE_PROJECT_REF, project_ref_from_database_url
from app.evaluation.answer_metrics import case_quality, evidence_coverage
from app.evaluation.metrics import aggregate_retrieval_metrics
from app.evaluation.reporting import MODES, render_final_report
from app.llm.agent import investigate
from app.llm.gemini_client import GeminiClient
from app.llm.schemas import MAX_LLM_REQUESTS
from app.llm.service import run_investigation
from app.model_cache import load_model


ROOT = Path(__file__).resolve().parents[2]
FINAL_CASES = ROOT / "eval" / "final_answer_eval.jsonl"
DEV_CASES = ROOT / "eval" / "retrieval_dev.jsonl"
DEFAULT_RESULTS = ROOT / "reports" / "final_evaluation_results.jsonl"
DEFAULT_LEDGER = ROOT / "reports" / ".final_evaluation_budget.jsonl"
DEFAULT_REPORT = ROOT / "reports" / "final_evaluation.md"
EVALUATION_THREADS = 1


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"JSONL row {line_number} must be an object")
            rows.append(row)
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_run_key(case_id: str, mode: str, dataset_sha256: str, model: str) -> str:
    value = "\0".join((case_id, mode, dataset_sha256, model))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_output(path: Path, dataset_sha256: str, model: str) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("dataset_sha256") != dataset_sha256:
                raise ValueError("results file belongs to a different evaluation dataset; choose a new --results path")
            if row.get("model") != model:
                raise ValueError("results file belongs to a different Gemini model; choose a new --results path")
            key = row.get("run_key")
            if not isinstance(key, str) or key in rows:
                raise ValueError(f"invalid or duplicate result key at line {line_number}")
            rows[key] = row
    return rows


def _recent_reservations(path: Path, *, now: datetime | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    cutoff = (now or _utc_now()) - timedelta(hours=24)
    return [row for row in _all_reservations(path)
            if datetime.fromisoformat(row["reserved_at"]) >= cutoff]


def _all_reservations(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            timestamp = datetime.fromisoformat(row["reserved_at"])
            if timestamp.tzinfo is None:
                raise ValueError("budget ledger contains a timestamp without a timezone")
            events.append(row)
    return events


def _acquire_ledger_lock(path: Path) -> None:
    """Acquire an exclusive local lock, clearing it only when its PID is gone."""
    for _ in range(2):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                owner = json.loads(path.read_text(encoding="utf-8"))
                pid = owner.get("pid")
                if type(pid) is not int or pid <= 0:
                    raise RuntimeError("evaluation lock is unreadable; inspect it before resuming")
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    path.unlink()
                    continue
                except PermissionError:
                    pass
                except OSError as exc:
                    if getattr(exc, "winerror", None) in {87, 1168}:
                        path.unlink()
                        continue
                    raise RuntimeError("could not determine whether the evaluation lock owner is running") from None
                raise RuntimeError("evaluation budget ledger is locked by a running process")
            except FileNotFoundError:
                continue
        else:
            with os.fdopen(descriptor, "w", encoding="utf-8") as lock:
                lock.write(json.dumps({"pid": os.getpid(), "started_at": _utc_now().isoformat()}))
            return
    raise RuntimeError("could not acquire evaluation budget ledger lock")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as target:
        target.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        target.flush()
        os.fsync(target.fileno())


def _repair_incomplete_result_tail(path: Path) -> None:
    """Keep completed JSONL rows if a process stopped while appending its last result."""
    if not path.exists():
        return
    with path.open("r+b") as target:
        content = target.read()
        if not content or content.endswith(b"\n"):
            return
        last_line_start = content.rfind(b"\n") + 1
        tail = content[last_line_start:]
        try:
            json.loads(tail.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            target.seek(last_line_start)
            target.truncate()
        else:
            target.seek(0, os.SEEK_END)
            target.write(b"\n")
        target.flush()
        os.fsync(target.fileno())


def reserve_investigation(
    ledger: Path, *, run_key: str, case_id: str, mode: str, daily_budget: int,
) -> bool:
    if daily_budget <= 0:
        return False
    recent = _recent_reservations(ledger)
    if len(recent) >= daily_budget:
        return False
    _append_jsonl(ledger, {
        "reserved_at": _utc_now().isoformat(), "run_key": run_key,
        "case_id": case_id, "mode": mode,
    })
    return True


def _ranked_unique_hits(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = []
    seen: set[str] = set()
    for item in sorted(results, key=lambda row: (row.get("tool_call_index", 0), row.get("rank", 0))):
        chunk_id = item.get("chunk_id")
        if not isinstance(chunk_id, str) or chunk_id in seen:
            continue
        seen.add(chunk_id)
        unique.append({
            "investigation_rank": len(unique) + 1,
            "chunk_id": chunk_id, "doc_id": item.get("doc_id"),
            "title": item.get("title"), "titles": item.get("titles") or [],
            "score": item.get("score"),
        })
    return unique


def _fixture_search(case: dict[str, Any]):
    hits = []
    for item in case["fixture_evidence"]:
        sentence = item["sentence"]
        title = item["title"]
        hits.append({
            "chunk_id": item["chunk_id"], "doc_id": item["doc_id"],
            "title": title, "titles": [title], "score": 1.0,
            "sources": [{"source_id": item["source_id"], "title_alias": title}],
            "evidence_text": sentence,
            "validation_source": {
                "full_text": sentence, "start_char": 0, "end_char": len(sentence),
            },
        })

    def search_fixture(_conn: Any, _query: str, **kwargs: Any) -> list[dict[str, Any]]:
        return hits[:kwargs.get("limit", len(hits))]

    return search_fixture


def run_fixture_investigation(
    case: dict[str, Any], *, settings: Settings,
) -> dict[str, Any]:
    """Run the real agent and citation validator against isolated synthetic evidence."""
    client = GeminiClient(settings)
    started = perf_counter()
    try:
        result = investigate(
            case["question"], conn=object(), embedding_model=None,
            llm_client=client, retrieval_mode="semantic",
            database_statement_timeout_ms=settings.database_statement_timeout_ms,
            deadline=started + settings.investigation_timeout_seconds,
            started_at=started,
            capture_evaluation_details=True,
            search_function=_fixture_search(case),
        )
        return result.as_dict()
    finally:
        client.close()


def _safe_retrieval_rows(trace: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in trace.get("evaluation_retrieval_results", []):
        rows.append({key: item.get(key) for key in (
            "chunk_id", "doc_id", "title", "titles", "score", "rank", "tool_call_index",
        )})
    return rows


def _failure_categories(
    case: dict[str, Any], quality: dict[str, Any],
    coverage: dict[str, Any] | None, trace: dict[str, Any], error_type: str | None,
) -> list[str]:
    """Assign cautious diagnostic labels; labels describe signals, not entailment judgments."""
    categories: list[str] = []
    generation_error = trace.get("generation_error")
    if error_type or generation_error:
        error = f"{error_type or ''} {generation_error or ''}".casefold()
        categories.append("timeout" if "timeout" in error else "llm_or_tool_error")

    expected = case.get("expected_status")
    predicted = quality.get("predicted_status")
    diagnostic = quality.get("evidence_diagnostic")
    support_fraction = coverage.get("coverage") if coverage else None
    if expected == "answered" and isinstance(support_fraction, (int, float)) and support_fraction < 1:
        categories.append("retrieval_miss")

    citation_diagnostics = {
        "evidence_retrieved_but_not_cited", "citation_rejected", "central_claim_unverified",
    }
    if diagnostic in citation_diagnostics:
        categories.append("invalid_or_missing_citation")

    if expected == "answered":
        if predicted == "insufficient" and not categories:
            categories.append("model_abstention")
        elif predicted == "answered" and quality.get("answer_correctness") is not True:
            if support_fraction == 1:
                categories.append(
                    "incorrect_multi_hop_reasoning" if case.get("category") == "multi_hop"
                    else "incorrect_single_hop_answer"
                )
        if (predicted == "answered" and quality.get("draft_citation_count") == 0
                and "invalid_or_missing_citation" not in categories):
            categories.append("invalid_or_missing_citation")
    elif expected == "insufficient" and predicted != "insufficient":
        categories.append("false_answer_on_unanswerable")
    elif expected == "conflicting" and predicted != "conflicting":
        categories.append("conflict_not_detected")
    return categories


def make_case_result(
    case: dict[str, Any], *, mode: str, raw_result: dict[str, Any] | None,
    dataset_sha256: str, model: str, error_type: str | None = None,
) -> dict[str, Any]:
    result = raw_result or {}
    trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
    raw_hits = trace.get("evaluation_retrieval_results", [])
    compact_hits = _safe_retrieval_rows(trace)
    ranked_hits = _ranked_unique_hits(raw_hits)
    quality = case_quality(case, result) if raw_result is not None else {
        "answer_correctness": False, "answer_span_match": None, "exact_match": None,
        "predicted_status": None, "citation_validity": None,
        "all_draft_citations_valid": None, "draft_citation_count": None,
        "verified_citation_count": None, "evidence_diagnostic": None,
    }
    coverage = evidence_coverage(case.get("supporting_evidence", []), raw_hits)
    api_usage = trace.get("api_usage", {})
    if error_type:
        error_reason = error_type
    elif quality.get("predicted_status") == "insufficient":
        error_reason = trace.get("generation_error") or quality.get("evidence_diagnostic")
    else:
        error_reason = None
    row = {
        "run_key": build_run_key(case["case_id"], mode, dataset_sha256, model),
        "dataset_sha256": dataset_sha256, "model": model,
        "case_id": case["case_id"],
        "category": case["category"], "execution_mode": case["execution_mode"],
        "retrieval_mode": mode, "question": case["question"],
        "expected_answer": case["gold_answer"], "expected_status": case["expected_status"],
        "predicted_answer": result.get("answer"), "predicted_claims": [
            {"claim_id": claim.get("claim_id"), "text": claim.get("text"),
             "citations": [{
                 "chunk_id": citation.get("chunk_id"), "doc_id": citation.get("doc_id"),
                 "titles": citation.get("titles", []), "quote": citation.get("quote"),
             } for citation in claim.get("citations", []) if isinstance(citation, dict)]}
            for claim in result.get("claims", []) if isinstance(claim, dict)
        ],
        **quality, "supporting_evidence_coverage": coverage,
        "retrieval_results": compact_hits,
        "retrieval_ranking_for_metrics": ranked_hits,
        "tool_call_count": len(trace.get("tool_calls", [])),
        "api_request_count": api_usage.get("request_count"),
        "api_request_latencies_seconds": api_usage.get("request_latencies_seconds", []),
        "latency_seconds": trace.get("total_investigation_seconds"),
        "abstention_or_error_reason": error_reason,
        "error_type": error_type,
    }
    row["failure_categories"] = _failure_categories(case, quality, coverage, trace, error_type)
    return row


def _percentile_summary(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "median_seconds": statistics.median(ordered),
        "p95_nearest_rank_seconds": ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)],
    }


def aggregate_results(
    cases: list[dict[str, Any]], rows: list[dict[str, Any]], modes: tuple[str, ...],
) -> dict[str, Any]:
    results: dict[str, Any] = {"modes": {}, "fixture_conflicts": {}}
    case_by_id = {case["case_id"]: case for case in cases}
    for mode in modes:
        mode_rows = [row for row in rows if row["retrieval_mode"] == mode
                     and row["execution_mode"] == "live"]
        mode_cases = [case_by_id[row["case_id"]] for row in mode_rows]
        successful = [row for row in mode_rows if row["error_type"] is None]
        answerable = [case for case in case_by_id.values()
                      if case["execution_mode"] == "live" and case["expected_status"] == "answered"]
        per_case = {row["case_id"]: row for row in mode_rows}
        evaluated_answerable = [case for case in answerable if case["case_id"] in per_case]
        retrieval_inputs = [
            {**case, "question_id": case["case_id"]}
            for case in evaluated_answerable
        ]
        retrieval_map = {
            case["case_id"]: per_case.get(case["case_id"], {}).get("retrieval_ranking_for_metrics", [])
            for case in evaluated_answerable
        }
        retrieval = aggregate_retrieval_metrics(retrieval_inputs, retrieval_map) if evaluated_answerable else None
        correct = sum(bool(row["answer_correctness"]) for row in mode_rows)
        span_rows = [row for row in mode_rows if row["category"] in {"multi_hop", "single_hop"}]
        answered_rows = [row for row in mode_rows if row.get("predicted_status") == "answered"]
        unanswerable_rows = [row for row in mode_rows if row["category"] == "unanswerable"]
        true_abstentions = sum(row.get("predicted_status") == "insufficient" for row in unanswerable_rows)
        predicted_abstentions = sum(row.get("predicted_status") == "insufficient" for row in mode_rows)
        citation_total = sum(row.get("draft_citation_count") or 0 for row in mode_rows)
        citation_valid = sum(row.get("verified_citation_count") or 0 for row in mode_rows)
        predicted_status_counts = {
            status: sum(row.get("predicted_status") == status for row in mode_rows)
            for status in ("answered", "insufficient", "conflicting")
        }
        evidence_references = sum(
            (row.get("supporting_evidence_coverage") or {}).get("support_references", 0)
            for row in mode_rows
        )
        evidence_found = sum(
            (row.get("supporting_evidence_coverage") or {}).get("support_references_retrieved", 0)
            for row in mode_rows
        )
        failure_categories: dict[str, int] = defaultdict(int)
        for row in mode_rows:
            for category in row.get("failure_categories", []):
                failure_categories[category] += 1
        failure_examples = [
            {
                "case_id": row["case_id"], "category": row["category"],
                "question": row["question"], "predicted_status": row.get("predicted_status"),
                "failure_categories": row.get("failure_categories", []),
                "evidence_diagnostic": row.get("evidence_diagnostic"),
                "supporting_evidence_coverage": (
                    row.get("supporting_evidence_coverage") or {}
                ).get("coverage"),
                "supporting_references_retrieved": (
                    row.get("supporting_evidence_coverage") or {}
                ).get("support_references_retrieved"),
                "supporting_references_total": (
                    row.get("supporting_evidence_coverage") or {}
                ).get("support_references"),
            }
            for row in mode_rows if row.get("failure_categories")
        ][:3]
        results["modes"][mode] = {
            "expected_live_cases": sum(case["execution_mode"] == "live" for case in cases),
            "completed_live_cases": len(mode_rows),
            "successful_live_cases": len(successful),
            "failed_investigations": len(mode_rows) - len(successful),
            "pending_cases": max(0, sum(case["execution_mode"] == "live" for case in cases) - len(mode_rows)),
            "answer_correctness": correct / len(mode_rows) if mode_rows else None,
            "answer_correct_cases": correct,
            "overall_correctness_denominator": len(mode_rows),
            "predicted_status_counts": predicted_status_counts,
            "answer_span_match_rate": sum(row["answer_span_match"] is True for row in span_rows) / len(span_rows) if span_rows else None,
            "strict_exact_match_rate": sum(row["exact_match"] is True for row in span_rows) / len(span_rows) if span_rows else None,
            "answerable_cases_completed": len(span_rows),
            "answered_question_accuracy": sum(row["answer_correctness"] for row in answered_rows) / len(answered_rows) if answered_rows else None,
            "answered_question_denominator": len(answered_rows),
            "abstention_precision": true_abstentions / predicted_abstentions if predicted_abstentions else None,
            "abstention_recall": true_abstentions / len(unanswerable_rows) if unanswerable_rows else None,
            "unanswerable_cases_completed": len(unanswerable_rows),
            "citation_validity": citation_valid / citation_total if citation_total else None,
            "valid_citations": citation_valid,
            "draft_citations": citation_total,
            "supporting_evidence_coverage": evidence_found / evidence_references if evidence_references else None,
            "supporting_references_retrieved": evidence_found,
            "supporting_references_total": evidence_references,
            "retrieval": retrieval,
            "investigation_latency": _percentile_summary([
                row["latency_seconds"] for row in successful
                if isinstance(row.get("latency_seconds"), (int, float))
            ]),
            "tool_calls": sum(row.get("tool_call_count", 0) for row in mode_rows),
            "api_requests": sum(row.get("api_request_count", 0) for row in mode_rows
                                 if isinstance(row.get("api_request_count"), int)),
            "failure_category_counts": dict(sorted(failure_categories.items())),
            "sanitized_failure_examples": failure_examples,
        }
    fixture_rows = [row for row in rows if row["execution_mode"] == "fixture"]
    fixture_correct = sum(row.get("predicted_status") == "conflicting" for row in fixture_rows)
    results["fixture_conflicts"] = {
        "scope": "agent and citation/conflict handling with injected synthetic evidence; no database retrieval",
        "expected": 7, "completed": len(fixture_rows),
        "failed_investigations": sum(row["error_type"] is not None for row in fixture_rows),
        "correct_conflict_detections": fixture_correct,
        "conflict_detection_accuracy": fixture_correct / len(fixture_rows) if fixture_rows else None,
    }
    return results


def audit_plan(
    cases: list[dict[str, Any]], *, dataset_sha256: str, daily_budget: int,
) -> dict[str, Any]:
    if len(cases) != 45:
        raise ValueError("final answer dataset must contain exactly 45 planned cases")
    expected_counts = {"multi_hop": 25, "single_hop": 5, "unanswerable": 8, "conflicting": 7}
    actual_counts = {category: sum(case.get("category") == category for case in cases)
                     for category in expected_counts}
    if actual_counts != expected_counts:
        raise ValueError("final answer dataset category mix differs from the audited plan")
    live_count = sum(case["execution_mode"] == "live" for case in cases)
    fixture_count = sum(case["execution_mode"] == "fixture" for case in cases)
    if live_count != 38 or fixture_count != 7:
        raise ValueError("final evaluation must include 38 live and 7 fixture-only cases")
    investigations = live_count * len(MODES) + fixture_count
    dev = read_jsonl(DEV_CASES)
    final_candidate_ids = {
        source_id for case in cases
        for source_id in (case.get("source_question_id"), case.get("derived_from_question_id"))
        if source_id
    }
    dev_ids = {case.get("question_id") for case in dev}
    if final_candidate_ids & dev_ids:
        raise ValueError("final answer cases overlap retrieval development question IDs")
    return {
        "status": "prepared_live_evaluation_pending",
        "dataset_sha256": dataset_sha256,
        "case_count": len(cases),
        "category_counts": actual_counts,
        "live_case_count": live_count,
        "fixture_only_case_count": fixture_count,
        "retrieval_development_count": len(dev),
        "question_id_sets_disjoint": True,
        "retrieval_modes": list(MODES),
        "planned_investigations_for_final_comparison": investigations,
        "max_gemini_http_requests_for_final_comparison": investigations * MAX_LLM_REQUESTS,
        "configured_local_daily_investigation_budget": daily_budget,
        "minimum_rolling_windows_at_local_budget": (
            math.ceil(investigations / daily_budget) if daily_budget > 0 else None
        ),
        "budget_check": "blocked_locally" if daily_budget == 0 else "see live plan against rolling 24-hour ledger",
        "gold_answer_handling": "runner passes only each question to the agent; expected answers remain in evaluator process",
    }


def check_indexed_coverage(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Read-only production coverage gate; verifies identity before any SQL."""
    from app.db.connection import connect_database
    from app.db.queries import read_indexed_source_evidence
    from app.evaluation.metrics import indexed_evidence_pairs, select_eligible_questions

    settings = Settings.load()
    if project_ref_from_database_url(settings.database_url) != EXPECTED_SUPABASE_PROJECT_REF:
        raise RuntimeError("DATABASE_URL does not identify the approved Frankfurt Evidence_AI project")
    answerable = [case for case in cases if case["category"] in {"multi_hop", "single_hop"}]
    with connect_database(autocommit=True) as conn:
        conn.execute("SET statement_timeout = '30000'")
        count = conn.execute("SELECT count(*) FROM public.documents").fetchone()[0]
        source_evidence = read_indexed_source_evidence(conn)
    pairs = indexed_evidence_pairs(source_evidence)
    eligible, excluded = select_eligible_questions(answerable, pairs)
    references = sum(len(case.get("supporting_evidence", [])) for case in answerable)
    found = sum(len(case.get("supporting_evidence", [])) for case in eligible)
    return {
        "project_ref": EXPECTED_SUPABASE_PROJECT_REF,
        "indexed_documents": count,
        "source_rows_read": len(source_evidence),
        "answerable_cases": len(answerable), "eligible_cases": len(eligible),
        "excluded_cases": [case["case_id"] for case in excluded],
        "supporting_sentence_references": references,
        "supporting_sentence_references_found": found,
        "supporting_sentence_coverage": found / references if references else 0.0,
        "database_access": "read_only_autocommit; no writes performed",
    }


def require_complete_indexed_coverage(
    cases: list[dict[str, Any]], coverage: dict[str, Any],
) -> None:
    """Fail closed unless the expected Frankfurt corpus contains every answerable fact."""
    answerable = [case for case in cases if case["category"] in {"multi_hop", "single_hop"}]
    expected_references = sum(len(case.get("supporting_evidence", [])) for case in answerable)
    if coverage.get("project_ref") != EXPECTED_SUPABASE_PROJECT_REF:
        raise RuntimeError("indexed-evidence check did not verify the approved Frankfurt project")
    if coverage.get("indexed_documents") != 50_000:
        raise RuntimeError("indexed-evidence check did not find the expected 50,000-document corpus")
    if coverage.get("eligible_cases") != len(answerable):
        raise RuntimeError("not every answerable final case has complete indexed evidence")
    if coverage.get("supporting_sentence_references_found") != expected_references:
        raise RuntimeError("indexed support-reference count does not match the final evaluation set")


def _run_one(
    case: dict[str, Any], mode: str, *, settings: Settings,
    model: Any | None,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        if case["execution_mode"] == "fixture":
            raw = run_fixture_investigation(case, settings=settings)
        else:
            raw = run_investigation(
                case["question"], settings=settings, model=model,
                retrieval_mode=mode, capture_evaluation_details=True,
            )
        return raw, None
    except Exception as exc:
        return None, type(exc).__name__


def run_live(
    *, cases: list[dict[str, Any]], modes: tuple[str, ...], dataset_sha256: str,
    settings: Settings, results_path: Path, ledger_path: Path,
    max_investigations: int | None = None,
) -> dict[str, Any]:
    if settings.investigation_daily_budget <= 0:
        raise RuntimeError("local INVESTIGATION_DAILY_BUDGET is 0; live evaluation is disabled")
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    if project_ref_from_database_url(settings.database_url) != EXPECTED_SUPABASE_PROJECT_REF:
        raise RuntimeError("DATABASE_URL does not identify the approved Frankfurt Evidence_AI project")
    if not modes or any(mode not in MODES for mode in modes):
        raise ValueError("retrieval modes must be selected from semantic, keyword, and hybrid")
    if max_investigations is not None and max_investigations < 1:
        raise ValueError("--max-investigations must be positive")

    model_name = settings.gemini_model or DEFAULT_GEMINI_MODEL
    mode_plan = [(case, "fixture" if case["execution_mode"] == "fixture" else mode)
                 for case in cases for mode in (modes if case["execution_mode"] == "live" else ("fixture",))]
    results_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = ledger_path.with_suffix(ledger_path.suffix + ".lock")
    _acquire_ledger_lock(lock_path)
    try:
        _repair_incomplete_result_tail(results_path)
        existing = _read_output(results_path, dataset_sha256, model_name)
        completed_keys = set(existing)
        reserved_keys = {item["run_key"] for item in _all_reservations(ledger_path)}
        plan_keys = {build_run_key(case["case_id"], mode, dataset_sha256, model_name)
                     for case, mode in mode_plan}
        uncertain_keys = (reserved_keys - completed_keys) & plan_keys
        pending = [(case, mode, build_run_key(case["case_id"], mode, dataset_sha256, model_name))
                   for case, mode in mode_plan
                   if build_run_key(case["case_id"], mode, dataset_sha256, model_name)
                   not in completed_keys | uncertain_keys]
        total_pending = len(pending)
        if max_investigations is not None:
            pending = pending[:max_investigations]
        if not pending:
            return {
                "status": "no_pending_cases", "completed": len(existing),
                "uncertain_inflight": len(uncertain_keys),
                "aggregate": aggregate_results(cases, list(existing.values()), modes),
            }
        budget_remaining = max(
            0, settings.investigation_daily_budget - len(_recent_reservations(ledger_path)),
        )
        if budget_remaining == 0:
            return {
                "status": "daily_budget_exhausted", "completed": len(existing),
                "pending_after_run": len(pending), "uncertain_inflight": len(uncertain_keys),
                "configured_local_daily_budget": settings.investigation_daily_budget,
                "aggregate": aggregate_results(cases, list(existing.values()), modes),
            }
        has_live = any(case["execution_mode"] == "live" for case, _, _ in pending)
        model = load_model("BAAI/bge-small-en-v1.5", threads=EVALUATION_THREADS) if has_live else None
        completed_this_run = 0
        for case, mode, run_key in pending:
            if not reserve_investigation(
                ledger_path, run_key=run_key, case_id=case["case_id"], mode=mode,
                daily_budget=settings.investigation_daily_budget,
            ):
                break
            raw, error_type = _run_one(case, mode, settings=settings, model=model)
            row = make_case_result(
                case, mode=mode, raw_result=raw,
                dataset_sha256=dataset_sha256, model=model_name, error_type=error_type,
            )
            _append_jsonl(results_path, row)
            existing[run_key] = row
            completed_this_run += 1
        aggregate = aggregate_results(cases, list(existing.values()), modes)
        left = max(0, total_pending - completed_this_run)
        return {
            "status": "complete" if left == 0 and not uncertain_keys else "partial_budget_or_interruption",
            "completed_this_run": completed_this_run,
            "completed_total": len(existing), "pending_after_run": left,
            "uncertain_inflight_not_retried": len(uncertain_keys),
            "configured_local_daily_budget": settings.investigation_daily_budget,
            "daily_budget_remaining_after_run": max(
                0, settings.investigation_daily_budget - len(_recent_reservations(ledger_path)),
            ),
            "aggregate": aggregate,
        }
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass

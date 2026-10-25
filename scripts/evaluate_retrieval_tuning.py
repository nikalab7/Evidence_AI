"""Evaluate keyword thresholds and a cached hybrid grid on the dev set only."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import statistics
import sys
from time import perf_counter
from typing import Any, Callable

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.db.connection import EXPECTED_SUPABASE_PROJECT_REF, connect_database
from app.db.queries import read_indexed_source_evidence
from app.embedding_smoke import MODEL_NAME
from app.evaluation.metrics import (
    aggregate_retrieval_metrics,
    indexed_evidence_pairs,
    score_question,
    select_eligible_questions,
)
from app.model_cache import load_model
from app.retrieval.keyword import retrieve_keyword
from app.retrieval.ranker import weighted_rrf
from app.retrieval.semantic import retrieve_semantic


TARGET_PROJECT_REF = "nldnpqhqrfwjgxcqeuru"
DEV_PATH = PROJECT_ROOT / "eval" / "retrieval_dev.jsonl"
EXPECTED_DEV_QUESTIONS = 200
TOP_K = 10
CANDIDATE_K = 20
INFORMATIVE_THRESHOLDS = (0.05, 0.10, 0.15)
STATEMENT_TIMEOUT_MS = 60_000


@dataclass(frozen=True)
class HybridConfig:
    semantic_weight: float
    keyword_weight: float
    rrf_k: int


HYBRID_GRID = tuple(
    HybridConfig(1.0, keyword_weight, rrf_k)
    for rrf_k in (20, 60)
    for keyword_weight in (0.0, 0.25, 0.5, 1.0)
)


def rank_cached_candidates(
    semantic_hits: list[dict[str, Any]],
    keyword_hits: list[dict[str, Any]],
    config: HybridConfig,
) -> list[dict[str, Any]]:
    """Fuse one shared pair of candidate lists under a grid configuration."""
    return weighted_rrf(
        semantic_hits,
        keyword_hits,
        semantic_weight=config.semantic_weight,
        keyword_weight=config.keyword_weight,
        rrf_k=config.rrf_k,
    )


def select_best_positive_hybrid(
    grid_summary: dict[str, dict[str, Any]],
) -> HybridConfig:
    """Select among hybrid variants that actually assign weight to keyword hits."""
    candidates = [config for config in HYBRID_GRID if config.keyword_weight > 0]
    return max(
        candidates,
        key=lambda config: (
            grid_summary[f"kw={config.keyword_weight:g},k={config.rrf_k}"]["metrics"]["recall@10"],
            grid_summary[f"kw={config.keyword_weight:g},k={config.rrf_k}"]["metrics"]["recall@5"],
            grid_summary[f"kw={config.keyword_weight:g},k={config.rrf_k}"]["metrics"]["mrr"],
            -grid_summary[f"kw={config.keyword_weight:g},k={config.rrf_k}"]["latency"]["p95_nearest_rank_ms"],
        ),
    )


def _read_dev_questions() -> list[dict[str, Any]]:
    questions = []
    with DEV_PATH.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                question = json.loads(line)
            except json.JSONDecodeError:
                raise ValueError(f"invalid dev JSON at line {line_number}") from None
            if not isinstance(question, dict):
                raise ValueError(f"dev row at line {line_number} must be an object")
            questions.append(question)
    if len(questions) != EXPECTED_DEV_QUESTIONS:
        raise RuntimeError("Phase 6A requires exactly the 200-question retrieval dev set")
    return questions


def _percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "median_ms": round(statistics.median(ordered) * 1000, 3),
        "p95_nearest_rank_ms": round(ordered[p95_index] * 1000, 3),
    }


def _candidate_ids(hits: list[dict[str, Any]]) -> list[str]:
    return [hit["chunk_id"] for hit in hits]


def _measured_call(
    callback: Callable[[], list[dict[str, Any]]], *, variant: str, question_id: str,
) -> tuple[list[dict[str, Any]], float]:
    started = perf_counter()
    try:
        hits = callback()
    except psycopg.Error as exc:
        raise RuntimeError(
            f"{variant} retrieval failed for dev question {question_id}; "
            f"SQLSTATE={exc.sqlstate or 'unknown'}"
        ) from None
    return hits, perf_counter() - started


def _titles(hits: list[dict[str, Any]], *, limit: int = 5) -> list[str]:
    return [
        title
        for hit in hits[:limit]
        for source in hit.get("sources", [])
        if isinstance(source, dict)
        for title in [source.get("title_alias")]
        if isinstance(title, str) and title
    ]


def _evaluate_candidates(
    questions: list[dict[str, Any]],
    candidates: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ranked = {question["question_id"]: candidates[question["question_id"]][:TOP_K]
              for question in questions}
    metrics = aggregate_retrieval_metrics(questions, ranked)
    detail_rows = []
    for question in questions:
        question_id = question["question_id"]
        detail_rows.append({
            "question_id": question_id,
            "question": question["question"],
            "supporting_titles": sorted({
                fact["title"] for fact in question.get("supporting_evidence", [])
                if isinstance(fact, dict) and isinstance(fact.get("title"), str)
            }),
            "metrics": score_question(question, ranked[question_id]),
            "top_titles": _titles(candidates[question_id]),
        })
    return metrics, detail_rows


def _worst_examples(detail_rows: list[dict[str, Any]], count: int = 3) -> list[dict[str, Any]]:
    return sorted(
        detail_rows,
        key=lambda row: (
            row["metrics"]["recall@10"],
            row["metrics"]["mrr"],
            row["question_id"],
        ),
    )[:count]


def run_tuning() -> dict[str, Any]:
    if EXPECTED_SUPABASE_PROJECT_REF != TARGET_PROJECT_REF:
        raise RuntimeError("application database guard differs from the Phase 6A target")
    questions = _read_dev_questions()
    thresholds = tuple(sorted(set(INFORMATIVE_THRESHOLDS)))
    if len(thresholds) != len(INFORMATIVE_THRESHOLDS):
        raise RuntimeError("informative-term thresholds must be unique")

    semantic_candidates: dict[str, list[dict[str, Any]]] = {}
    semantic_seconds: list[float] = []
    original_keyword_candidates: dict[str, list[dict[str, Any]]] = {}
    original_keyword_seconds: list[float] = []
    informative_candidates = {
        threshold: {} for threshold in thresholds
    }
    informative_seconds = {threshold: [] for threshold in thresholds}

    with connect_database(autocommit=True) as conn:
        conn.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT_MS}ms'")
        document_count = conn.execute(
            "SELECT count(*) FROM public.documents"
        ).fetchone()[0]
        if document_count != 50_000:
            raise RuntimeError("Phase 6A requires the verified 50,000-document corpus")
        source_evidence = read_indexed_source_evidence(conn)
        eligible, excluded = select_eligible_questions(
            questions, indexed_evidence_pairs(source_evidence),
        )
        if len(eligible) != EXPECTED_DEV_QUESTIONS or excluded:
            raise RuntimeError(
                "all 200 retrieval dev questions must have complete indexed evidence"
            )
        model = load_model(MODEL_NAME)

        # Pass 1: fetch semantic candidates once and each informative threshold once.
        for question_number, question in enumerate(eligible, start=1):
            question_id = question["question_id"]
            semantic_candidates[question_id], elapsed = _measured_call(
                lambda: retrieve_semantic(
                    conn, model, question["question"], limit=CANDIDATE_K,
                ),
                variant="semantic", question_id=question_id,
            )
            semantic_seconds.append(elapsed)

            original_keyword_candidates[question_id], elapsed = _measured_call(
                lambda: retrieve_keyword(
                    conn, question["question"], limit=CANDIDATE_K, strategy="or",
                ),
                variant="original_or_keyword", question_id=question_id,
            )
            original_keyword_seconds.append(elapsed)

            for threshold in thresholds:
                informative_candidates[threshold][question_id], elapsed = _measured_call(
                    lambda: retrieve_keyword(
                        conn,
                        question["question"],
                        limit=CANDIDATE_K,
                        strategy="informative",
                        common_term_threshold=threshold,
                    ),
                    variant=f"informative_{threshold:g}", question_id=question_id,
                )
                informative_seconds[threshold].append(elapsed)
            if question_number % 10 == 0 or question_number == len(eligible):
                print(
                    f"pass=1 completed={question_number}/{len(eligible)}",
                    file=sys.stderr, flush=True,
                )

        semantic_metrics, semantic_details = _evaluate_candidates(
            eligible, semantic_candidates,
        )
        original_keyword_metrics, original_keyword_details = _evaluate_candidates(
            eligible, original_keyword_candidates,
        )
        threshold_results: dict[float, dict[str, Any]] = {}
        for threshold in thresholds:
            metrics, details = _evaluate_candidates(
                eligible, informative_candidates[threshold],
            )
            threshold_results[threshold] = {
                "metrics": metrics,
                "latency": _percentiles(informative_seconds[threshold]),
                "worst_examples": _worst_examples(details),
                "details": details,
            }

        # Quality is primary; latency breaks ties after R@10, R@5, then MRR.
        best_threshold = max(
            thresholds,
            key=lambda threshold: (
                threshold_results[threshold]["metrics"]["recall@10"],
                threshold_results[threshold]["metrics"]["recall@5"],
                threshold_results[threshold]["metrics"]["mrr"],
                -threshold_results[threshold]["latency"]["p95_nearest_rank_ms"],
            ),
        )

        # Pass 2: one real end-to-end semantic + selected-keyword fetch per question.
        # All eight RRF configurations reuse these identical candidate lists.
        hybrid_fetch_seconds: list[float] = []
        grid_fusion_seconds: dict[HybridConfig, list[float]] = {
            config: [] for config in HYBRID_GRID
        }
        grid_results: dict[HybridConfig, dict[str, list[dict[str, Any]]]] = {
            config: {} for config in HYBRID_GRID
        }

        for question_number, question in enumerate(eligible, start=1):
            question_id = question["question_id"]
            semantic_hits, semantic_elapsed = _measured_call(
                lambda: retrieve_semantic(
                    conn, model, question["question"], limit=CANDIDATE_K,
                ),
                variant="grid_semantic", question_id=question_id,
            )
            keyword_hits, keyword_elapsed = _measured_call(
                lambda: retrieve_keyword(
                    conn,
                    question["question"],
                    limit=CANDIDATE_K,
                    strategy="informative",
                    common_term_threshold=best_threshold,
                ),
                variant="grid_informative_keyword", question_id=question_id,
            )
            fetch_elapsed = semantic_elapsed + keyword_elapsed
            hybrid_fetch_seconds.append(fetch_elapsed)

            if _candidate_ids(semantic_hits) != _candidate_ids(semantic_candidates[question_id]):
                raise RuntimeError("semantic candidate list changed between tuning passes")
            if _candidate_ids(keyword_hits) != _candidate_ids(
                informative_candidates[best_threshold][question_id]
            ):
                raise RuntimeError("informative keyword candidates changed between passes")

            for config in HYBRID_GRID:
                fusion_started = perf_counter()
                fused = rank_cached_candidates(semantic_hits, keyword_hits, config)
                fusion_elapsed = perf_counter() - fusion_started
                grid_fusion_seconds[config].append(fusion_elapsed)
                grid_results[config][question_id] = fused[:TOP_K]
            if question_number % 10 == 0 or question_number == len(eligible):
                print(
                    f"pass=2 completed={question_number}/{len(eligible)}",
                    file=sys.stderr, flush=True,
                )

        grid_summary = {}
        grid_details: dict[HybridConfig, list[dict[str, Any]]] = {}
        for config in HYBRID_GRID:
            metrics, details = _evaluate_candidates(eligible, grid_results[config])
            combined_latency = [
                fetch + fusion
                for fetch, fusion in zip(hybrid_fetch_seconds, grid_fusion_seconds[config])
            ]
            key = f"kw={config.keyword_weight:g},k={config.rrf_k}"
            grid_summary[key] = {
                "config": asdict(config),
                "metrics": metrics,
                "latency": _percentiles(combined_latency),
                "fusion_only_latency": _percentiles(grid_fusion_seconds[config]),
                "worst_examples": _worst_examples(details),
            }
            grid_details[config] = details

        best_hybrid = select_best_positive_hybrid(grid_summary)

        best_key = f"kw={best_hybrid.keyword_weight:g},k={best_hybrid.rrf_k}"
        selected_keyword = threshold_results[best_threshold]
        output = {
            "status": "passed",
            "project_ref": TARGET_PROJECT_REF,
            "dataset": "eval/retrieval_dev.jsonl",
            "question_count": len(eligible),
            "excluded_questions": len(excluded),
            "indexed_documents": document_count,
            "settings": {
                "top_k": TOP_K,
                "candidate_k": CANDIDATE_K,
                "keyword_thresholds": thresholds,
                "hybrid_configs": [asdict(config) for config in HYBRID_GRID],
                "keyword_selection_rule": "maximize R@10, then R@5, then MRR, then lower p95",
            },
            "semantic_only": {
                "metrics": semantic_metrics,
                "latency": _percentiles(semantic_seconds),
                "worst_examples": _worst_examples(semantic_details),
            },
            "original_or_keyword": {
                "metrics": original_keyword_metrics,
                "latency": _percentiles(original_keyword_seconds),
                "worst_examples": _worst_examples(original_keyword_details),
            },
            "informative_keyword_variants": {
                str(threshold): {
                    key: value for key, value in result.items() if key != "details"
                }
                for threshold, result in threshold_results.items()
            },
            "selected_keyword_threshold": best_threshold,
            "selected_keyword": {
                "metrics": selected_keyword["metrics"],
                "latency": _percentiles(informative_seconds[best_threshold]),
                "worst_examples": selected_keyword["worst_examples"],
            },
            "hybrid_grid": grid_summary,
            "selected_hybrid": {"key": best_key, **grid_summary[best_key]},
            "selection_note": (
                "selected_hybrid excludes keyword_weight=0 because that is semantic-only; "
                "the zero-weight rows remain in the full requested grid"
            ),
            "candidate_cache_checks": {
                "semantic_lists_identical_across_passes": True,
                "selected_keyword_lists_identical_across_passes": True,
                "grid_retrieval_passes": len(eligible),
                "sql_queries_repeated_per_grid_configuration": 0,
                "grid_uses_identical_semantic_and_keyword_candidates": True,
            },
            "latency_definition": (
                "semantic+keyword retrieval wall time on one reused connection plus each measured RRF call; "
                "model initialization and database connection establishment are excluded"
            ),
        }
        return output


def main() -> int:
    try:
        result = run_tuning()
    except psycopg.Error as exc:
        print(json.dumps({
            "status": "failed", "error": "database_error",
            "error_type": type(exc).__name__, "sqlstate": exc.sqlstate,
        }), file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({
            "status": "failed", "error_type": type(exc).__name__, "message": str(exc),
        }), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Evaluate retrieval only on dev questions fully evidenced in indexed Supabase rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time
from collections.abc import Mapping, Sequence
from typing import Any

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.db.connection import EXPECTED_SUPABASE_PROJECT_REF, connect_database
from app.db.queries import read_indexed_source_evidence_for_references
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


DEV_PATH = PROJECT_ROOT / "eval" / "retrieval_dev.jsonl"
TOP_K = 10
CANDIDATE_K = 20


def _read_questions(path: Path) -> list[dict[str, Any]]:
    questions = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                raise ValueError(f"invalid evaluation JSON at line {line_number}") from None
            if not isinstance(item, dict):
                raise ValueError(f"evaluation row at line {line_number} must be an object")
            questions.append(item)
    return questions


def _percentiles(values: Sequence[float]) -> dict[str, float]:
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "minimum_ms": round(ordered[0] * 1000, 3),
        "median_ms": round(statistics.median(ordered) * 1000, 3),
        "p95_nearest_rank_ms": round(ordered[index] * 1000, 3),
        "maximum_ms": round(ordered[-1] * 1000, 3),
    }


def _gold_titles(question: Mapping[str, Any]) -> set[str]:
    from app.ingestion.corpus_core import normalize_text

    return {
        normalize_text(fact["title"])
        for fact in question.get("supporting_evidence", [])
        if isinstance(fact, Mapping) and isinstance(fact.get("title"), str)
    }


def _compact_hits(
    question: Mapping[str, Any], hits: Sequence[Mapping[str, Any]], limit: int = 5,
) -> list[dict[str, Any]]:
    from app.ingestion.corpus_core import normalize_text

    gold = _gold_titles(question)
    output = []
    for rank, hit in enumerate(hits[:limit], start=1):
        sources = hit.get("sources") or []
        titles = sorted({source.get("title_alias", "") for source in sources if source.get("title_alias")})
        output.append({
            "rank": rank,
            "chunk_id": hit["chunk_id"],
            "doc_id": hit["doc_id"],
            "titles": titles,
            "supports_gold_title": any(normalize_text(title) in gold for title in titles),
            "score": hit.get("score"),
        })
    return output


def run_evaluation(
    *,
    dev_path: Path = DEV_PATH,
    question_rows: Sequence[Mapping[str, Any]] | None = None,
    require_all_eligible: bool = False,
    expected_indexed_documents: int | None = None,
    dataset_sha256: str | None = None,
    top_k: int = TOP_K,
    candidate_k: int = CANDIDATE_K,
    semantic_weight: float = 1.0,
    keyword_weight: float = 1.0,
    rrf_k: int = 60,
    details_json: Path | None = None,
) -> dict[str, Any]:
    if not 1 <= top_k <= candidate_k <= 100:
        raise ValueError("retrieval evaluation requires 1 <= top_k <= candidate_k <= 100")
    questions = ([dict(question) for question in question_rows]
                 if question_rows is not None else _read_questions(dev_path))
    if not questions:
        raise ValueError("retrieval dev file contains no questions")
    for question in questions:
        if not isinstance(question.get("question_id"), str):
            case_id = question.get("case_id")
            if isinstance(case_id, str):
                question["question_id"] = case_id
            else:
                raise ValueError("retrieval case requires question_id or case_id")
    required_evidence = [
        fact for question in questions for fact in question.get("supporting_evidence", [])
    ]

    with connect_database(autocommit=True) as conn:
        conn.execute("SET statement_timeout = '30000'")
        source_evidence = read_indexed_source_evidence_for_references(conn, required_evidence)
        indexed_documents = conn.execute("SELECT count(*) FROM public.documents").fetchone()[0]
        if expected_indexed_documents is not None and indexed_documents != expected_indexed_documents:
            raise RuntimeError(
                f"expected {expected_indexed_documents} indexed documents, found {indexed_documents}"
            )
        evidence_pairs = indexed_evidence_pairs(source_evidence)
        eligible, excluded = select_eligible_questions(questions, evidence_pairs)
        if not eligible:
            raise ValueError("no dev questions have complete supporting evidence in the indexed corpus")
        if require_all_eligible and excluded:
            raise RuntimeError(
                f"indexed evidence is incomplete for {len(excluded)} of {len(questions)} requested questions"
            )

        model = load_model(MODEL_NAME)
        results = {"semantic": {}, "keyword": {}, "hybrid": {}}
        latency = {"semantic": [], "keyword": [], "hybrid": []}
        example_data: dict[str, dict[str, dict[str, Any]]] = {}

        for question in eligible:
            question_id = question["question_id"]
            text = question["question"]
            hybrid_started = time.perf_counter()

            semantic_started = time.perf_counter()
            semantic_hits = retrieve_semantic(
                conn, model, text, limit=candidate_k,
            )
            latency["semantic"].append(time.perf_counter() - semantic_started)

            keyword_started = time.perf_counter()
            keyword_hits = retrieve_keyword(conn, text, limit=candidate_k)
            latency["keyword"].append(time.perf_counter() - keyword_started)

            hybrid_hits = weighted_rrf(
                semantic_hits,
                keyword_hits,
                semantic_weight=semantic_weight,
                keyword_weight=keyword_weight,
                rrf_k=rrf_k,
            )
            latency["hybrid"].append(time.perf_counter() - hybrid_started)

            results["semantic"][question_id] = semantic_hits[:top_k]
            results["keyword"][question_id] = keyword_hits[:top_k]
            results["hybrid"][question_id] = hybrid_hits[:top_k]
            example_data[question_id] = {
                "semantic": {"hits": semantic_hits, "metrics": score_question(question, semantic_hits[:top_k])},
                "keyword": {"hits": keyword_hits, "metrics": score_question(question, keyword_hits[:top_k])},
                "hybrid": {"hits": hybrid_hits, "metrics": score_question(question, hybrid_hits[:top_k])},
            }

    metrics = {
        mode: aggregate_retrieval_metrics(eligible, results[mode])
        for mode in ("semantic", "keyword", "hybrid")
    }
    hybrid_quality = [
        (example_data[question["question_id"]]["hybrid"]["metrics"]["recall@10"],
         example_data[question["question_id"]]["hybrid"]["metrics"]["mrr"],
         question)
        for question in eligible
    ]
    best_question = max(hybrid_quality, key=lambda row: (row[0], row[1], row[2]["question_id"]))[2]
    worst_question = min(hybrid_quality, key=lambda row: (row[0], row[1], row[2]["question_id"]))[2]
    example_questions = [best_question]
    if worst_question["question_id"] != best_question["question_id"]:
        example_questions.append(worst_question)

    examples = []
    for question in example_questions:
        question_id = question["question_id"]
        examples.append({
            "question_id": question_id,
            "question": question["question"],
            "supporting_titles": sorted(_gold_titles(question)),
            "modes": {
                mode: {
                    "metrics": example_data[question_id][mode]["metrics"],
                    "top_hits": _compact_hits(
                        question, example_data[question_id][mode]["hits"], limit=5,
                    ),
                }
                for mode in ("semantic", "keyword", "hybrid")
            },
        })

    if details_json is not None:
        details = {
            "dataset_sha256": dataset_sha256,
            "database_project_ref": EXPECTED_SUPABASE_PROJECT_REF,
            "indexed_documents": indexed_documents,
            "dev_questions_total": len(questions),
            "eligible_questions": len(eligible),
            "excluded_questions": len(excluded),
            "top_k": top_k,
            "candidate_k": candidate_k,
            "hybrid_weights": {
                "semantic": semantic_weight,
                "keyword": keyword_weight,
                "rrf_k": rrf_k,
            },
            "metrics": metrics,
            "latency": {
                mode: _percentiles(values) for mode, values in latency.items()
            },
            "per_question": [
                {
                    "question_id": question["question_id"],
                    "modes": {
                        mode: {
                            "metrics": example_data[question["question_id"]][mode]["metrics"],
                            "top_hits": _compact_hits(
                                question,
                                example_data[question["question_id"]][mode]["hits"],
                                limit=top_k,
                            ),
                        }
                        for mode in ("semantic", "keyword", "hybrid")
                    },
                }
                for question in eligible
            ],
        }
        details_json.write_text(json.dumps(details, indent=2), encoding="utf-8")

    return {
        "status": "passed",
        "dataset": (
            str(dev_path.relative_to(PROJECT_ROOT)) if dev_path.is_relative_to(PROJECT_ROOT)
            else str(dev_path)
        ) if question_rows is None else "provided_question_rows",
        "dataset_sha256": dataset_sha256,
        "embedding_model": MODEL_NAME,
        "indexed_documents": indexed_documents,
        "indexed_provenance_rows": len({source["source_id"] for source in source_evidence}),
        "dev_questions_total": len(questions),
        "eligible_questions": len(eligible),
        "excluded_incomplete_evidence_questions": len(excluded),
        "eligible_rule": "every supporting title/sentence pair must exist in provenance and indexed paragraph text after normalization",
        "metric_relevance_rule": "a retrieved chunk is relevant when any source title alias matches a gold supporting title",
        "top_k": top_k,
        "candidate_k": candidate_k,
        "hybrid_weights": {"semantic": semantic_weight, "keyword": keyword_weight, "rrf_k": rrf_k},
        "metrics": metrics,
        "latency": {mode: _percentiles(values) for mode, values in latency.items()},
        "examples": examples,
        "retrieval_quality_note": "title-level retrieval metrics only; they do not assess sentence entailment or answer correctness",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev", type=Path, default=DEV_PATH)
    parser.add_argument(
        "--answerable-only", action="store_true",
        help="score only live answerable cases from a final evaluation JSONL",
    )
    parser.add_argument("--top-k", type=int, default=TOP_K)
    parser.add_argument("--candidate-k", type=int, default=CANDIDATE_K)
    parser.add_argument("--semantic-weight", type=float, default=1.0)
    parser.add_argument("--keyword-weight", type=float, default=1.0)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument(
        "--details-json", type=Path,
        help="optional path for per-question metrics and ranked result IDs",
    )
    args = parser.parse_args()
    try:
        question_rows = None
        dataset_sha256 = None
        if args.answerable_only:
            all_rows = _read_questions(args.dev)
            dataset_sha256 = hashlib.sha256(args.dev.read_bytes()).hexdigest()
            question_rows = [
                {**row, "question_id": row.get("question_id") or row.get("case_id")}
                for row in all_rows
                if row.get("expected_status") == "answered"
                and row.get("execution_mode", "live") == "live"
            ]
            if not question_rows:
                raise ValueError("final evaluation file has no live answerable cases")
        report = run_evaluation(
            dev_path=args.dev, question_rows=question_rows,
            require_all_eligible=args.answerable_only,
            dataset_sha256=dataset_sha256,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
            semantic_weight=args.semantic_weight,
            keyword_weight=args.keyword_weight,
            rrf_k=args.rrf_k,
            details_json=args.details_json,
        )
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
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

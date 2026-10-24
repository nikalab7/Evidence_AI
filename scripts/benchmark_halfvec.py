"""Compare exact vector and halfvec-cast retrieval without changing the schema."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import sys
import time
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.db.connection import connect_database
from app.db.queries import read_indexed_source_evidence
from app.embedding_smoke import MODEL_NAME
from app.evaluation.metrics import (
    aggregate_retrieval_metrics,
    indexed_evidence_pairs,
    select_eligible_questions,
)
from app.ingestion.corpus_core import normalize_text
from app.model_cache import load_model


DEV_PATH = PROJECT_ROOT / "eval" / "retrieval_dev.jsonl"
LIMIT = 10

EXACT_DISTANCE = "c.embedding OPERATOR(extensions.<=>) q.embedding"
HALFVEC_DISTANCE = (
    "c.embedding::extensions.halfvec(384) "
    "OPERATOR(extensions.<=>) q.embedding::extensions.halfvec(384)"
)

RANK_SQL = """WITH query_vector AS (
        SELECT %s::extensions.vector(384) AS embedding
    )
    SELECT c.chunk_id, c.doc_id, {distance} AS cosine_distance,
           COALESCE(p.sources, '[]'::jsonb) AS sources
    FROM public.chunks c
    CROSS JOIN query_vector q
    LEFT JOIN LATERAL (
        SELECT jsonb_agg(jsonb_build_object('title_alias', s.title_alias)
                         ORDER BY s.title_normalized, s.source_id) AS sources
        FROM public.document_sources s WHERE s.doc_id = c.doc_id
    ) p ON TRUE
    WHERE c.chunking_strategy = 'paragraph'
    ORDER BY {distance}, c.chunk_id
    LIMIT %s"""


def _read_questions(path: Path) -> list[dict[str, Any]]:
    questions = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                question = json.loads(line)
            except json.JSONDecodeError:
                raise ValueError(f"invalid evaluation JSON at line {line_number}") from None
            if not isinstance(question, dict):
                raise ValueError(f"evaluation row {line_number} must be an object")
            questions.append(question)
    return questions


def _vector_literal(vector: Any) -> str:
    values = [float(value) for value in vector]
    if len(values) != 384 or not all(math.isfinite(value) for value in values):
        raise ValueError("query embedding must contain 384 finite values")
    return "[" + ",".join(format(value, ".9g") for value in values) + "]"


def _rank(conn: Any, vector: Any, *, halfvec: bool) -> tuple[list[dict[str, Any]], float]:
    distance = HALFVEC_DISTANCE if halfvec else EXACT_DISTANCE
    statement = RANK_SQL.format(distance=distance)
    started = time.perf_counter()
    rows = conn.execute(statement, (_vector_literal(vector), LIMIT)).fetchall()
    elapsed = time.perf_counter() - started
    hits = []
    for chunk_id, doc_id, cosine_distance, sources in rows:
        titles = sorted({
            source["title_alias"] for source in (sources or [])
            if isinstance(source, dict) and source.get("title_alias")
        }, key=lambda title: (normalize_text(title), title))
        hits.append({
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "titles": titles,
            "sources": sources or [],
            "score": 1.0 - float(cosine_distance),
        })
    return hits, elapsed


def run(path: Path = DEV_PATH) -> dict[str, Any]:
    questions = _read_questions(path)
    with connect_database() as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '60000'")
        conn.execute("SET LOCAL enable_indexscan = off")
        conn.execute("SET LOCAL enable_bitmapscan = off")
        evidence = read_indexed_source_evidence(conn)
        eligible, excluded = select_eligible_questions(
            questions, indexed_evidence_pairs(evidence),
        )
        document_count = conn.execute("SELECT count(*) FROM public.documents").fetchone()[0]
        if not eligible:
            raise ValueError("no evaluation questions have complete indexed evidence")

        model = load_model(MODEL_NAME)
        query_vectors = list(model.query_embed([item["question"] for item in eligible]))
        if len(query_vectors) != len(eligible):
            raise ValueError("embedding model returned an unexpected query count")

        results: dict[str, dict[str, list[dict[str, Any]]]] = {
            "vector": {}, "halfvec": {},
        }
        times: dict[str, list[float]] = {"vector": [], "halfvec": []}
        top10_overlap = []
        top10_order_matches = 0
        for question, vector in zip(eligible, query_vectors):
            question_id = question["question_id"]
            vector_hits, vector_seconds = _rank(conn, vector, halfvec=False)
            halfvec_hits, halfvec_seconds = _rank(conn, vector, halfvec=True)
            results["vector"][question_id] = vector_hits
            results["halfvec"][question_id] = halfvec_hits
            times["vector"].append(vector_seconds)
            times["halfvec"].append(halfvec_seconds)
            exact_ids = {hit["chunk_id"] for hit in vector_hits[:10]}
            half_ids = {hit["chunk_id"] for hit in halfvec_hits[:10]}
            top10_overlap.append(len(exact_ids & half_ids) / 10)
            if [hit["chunk_id"] for hit in vector_hits[:10]] == [
                hit["chunk_id"] for hit in halfvec_hits[:10]
            ]:
                top10_order_matches += 1

    return {
        "status": "passed",
        "method": "exhaustive PostgreSQL distance order; no halfvec column or index created",
        "indexed_documents": document_count,
        "dev_questions_total": len(questions),
        "eligible_questions": len(eligible),
        "excluded_questions": len(excluded),
        "top_k": LIMIT,
        "metrics": {
            precision: aggregate_retrieval_metrics(eligible, result)
            for precision, result in results.items()
        },
        "mean_top10_chunk_overlap": round(statistics.mean(top10_overlap), 4),
        "questions_with_identical_top10_set": sum(value == 1.0 for value in top10_overlap),
        "questions_with_identical_top10_order": top10_order_matches,
        "median_database_search_ms": {
            precision: round(statistics.median(samples) * 1000, 3)
            for precision, samples in times.items()
        },
        "accuracy_note": (
            "This isolates float16 quantization of stored and query vectors; it does not "
            "measure HNSW approximation, production schema changes, or answer entailment."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev", type=Path, default=DEV_PATH)
    args = parser.parse_args()
    print(json.dumps(run(args.dev), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

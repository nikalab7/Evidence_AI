"""Run one natural-language retrieval query against the configured database."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.db.connection import connect_database
from app.embedding_smoke import MODEL_NAME
from app.model_cache import load_model
from app.retrieval.engine import search


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="natural-language question")
    parser.add_argument("--mode", choices=("semantic", "keyword", "hybrid"), default="hybrid")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--candidate-limit", type=int, default=20)
    parser.add_argument("--semantic-weight", type=float, default=1.0)
    parser.add_argument("--keyword-weight", type=float, default=1.0)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--source-split")
    parser.add_argument("--chunking-strategy")
    parser.add_argument("--embedding-model")
    args = parser.parse_args()

    filters = {
        key: value for key, value in {
            "source_split": args.source_split,
            "chunking_strategy": args.chunking_strategy,
            "embedding_model": args.embedding_model,
        }.items() if value is not None
    }
    model: Any | None = None
    model_seconds = 0.0
    try:
        if args.mode in ("semantic", "hybrid"):
            model_started = time.perf_counter()
            model = load_model(MODEL_NAME)
            model_seconds = time.perf_counter() - model_started
        started = time.perf_counter()
        with connect_database(autocommit=True) as conn:
            conn.execute("SET statement_timeout = '30000'")
            hits = search(
                conn,
                args.query,
                mode=args.mode,
                limit=args.limit,
                candidate_limit=args.candidate_limit,
                model=model,
                filters=filters,
                semantic_weight=args.semantic_weight,
                keyword_weight=args.keyword_weight,
                rrf_k=args.rrf_k,
            )
        report = {
            "status": "passed",
            "query": args.query,
            "mode": args.mode,
            "filters": filters,
            "ranking": {
                "semantic_weight": args.semantic_weight,
                "keyword_weight": args.keyword_weight,
                "rrf_k": args.rrf_k,
            } if args.mode == "hybrid" else None,
            "embedding_model": MODEL_NAME if model is not None else None,
            "model_initialization_seconds": round(model_seconds, 3),
            "retrieval_seconds": round(time.perf_counter() - started, 3),
            "results": hits,
        }
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

"""Print sanitized Supabase database and ingestion-table size/count metrics."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.db.connection import connect_database
from app.db.queries import read_database_metrics


def main() -> int:
    try:
        with connect_database(autocommit=True) as conn:
            conn.execute("SET statement_timeout = '10000'")
            metrics = read_database_metrics(conn)
    except psycopg.Error as exc:
        print(json.dumps({
            "status": "failed", "error": "database_error",
            "error_type": type(exc).__name__, "sqlstate": exc.sqlstate,
        }), file=sys.stderr)
        return 1
    print(json.dumps({"status": "passed", **metrics}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

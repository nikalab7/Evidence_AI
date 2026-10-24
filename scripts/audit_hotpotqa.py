"""Stream HotpotQA and write exact corpus/evidence counts without ingestion."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from itertools import islice
from pathlib import Path
from typing import Any

from app.ingestion.hotpotqa_audit import (
    DATASET_CONFIG,
    DATASET_ID,
    DATASET_REVISION,
    audit_hotpotqa_splits,
)


def _load_split(load_dataset: Any, split: str, cache_dir: str) -> Any:
    return load_dataset(
        DATASET_ID,
        name=DATASET_CONFIG,
        split=split,
        revision=DATASET_REVISION,
        streaming=True,
        token=False,
        cache_dir=cache_dir,
    )


def _progress(split: str, rows: int) -> None:
    print(f"Scanned {rows:,} {split} questions", file=sys.stderr)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("reports/hotpotqa_audit.json"),
        help="Aggregate JSON report path (default: reports/hotpotqa_audit.json)",
    )
    parser.add_argument(
        "--max-rows", type=int,
        help="Optional smoke-run limit per split; such a report is explicitly partial.",
    )
    args = parser.parse_args()
    if args.max_rows is not None and args.max_rows < 1:
        parser.error("--max-rows must be positive")
    return args


def main() -> int:
    args = _parse_args()
    cache_parent = Path("data/cache")
    cache_parent.mkdir(parents=True, exist_ok=True)

    try:
        with tempfile.TemporaryDirectory(prefix="hotpotqa-audit-", dir=cache_parent) as cache_dir:
            os.environ["HF_HOME"] = cache_dir
            os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
            from datasets import __version__ as datasets_version
            from datasets import load_dataset

            train_rows = _load_split(load_dataset, "train", cache_dir)
            validation_rows = _load_split(load_dataset, "validation", cache_dir)
            if args.max_rows is not None:
                train_rows = islice(train_rows, args.max_rows)
                validation_rows = islice(validation_rows, args.max_rows)
            report = audit_hotpotqa_splits(
                train_rows, validation_rows, progress=_progress,
            )
            report["scan"] = {
                "complete": args.max_rows is None,
                "max_rows_per_split": args.max_rows,
                "datasets_library_version": datasets_version,
                "streaming": True,
                "raw_rows_written_to_project": False,
            }
    except ImportError:
        print("Install the optional audit dependency with: python -m pip install -r requirements-audit.txt",
              file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"HotpotQA audit failed ({type(exc).__name__}); no records were ingested.", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

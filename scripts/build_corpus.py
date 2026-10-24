"""Build a reproducible HotpotQA corpus locally; this script never writes to a database."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.ingestion.hotpotqa_corpus import build_hotpotqa_corpus


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Stable SHA-256 sampling seed (default: 42).",
    )
    parser.add_argument(
        "--write-large-files", action="store_true",
        help="Write the 200-line retrieval dev set and 50,000-line corpus after explicit approval.",
    )
    return parser.parse_args()


def _write_jsonl(path: Path, records: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")) + "\n")


def main() -> int:
    args = _arguments()
    try:
        from datasets import __version__ as datasets_version
        from datasets import load_dataset
    except ImportError:
        print(
            "Install the declared local audit dependency: "
            "python -m pip install -r requirements-audit.txt", file=sys.stderr,
        )
        return 2
    try:
        report, corpus, dev_cases, candidates = build_hotpotqa_corpus(
            load_dataset, datasets_version, args.seed, PROJECT_ROOT / "data" / "cache",
        )
    except Exception as exc:
        print(
            f"Corpus audit failed ({type(exc).__name__}); "
            "no database or embedding was used.", file=sys.stderr,
        )
        return 2

    corpus_path = PROJECT_ROOT / "data" / "corpus.jsonl"
    dev_path = PROJECT_ROOT / "eval" / "retrieval_dev.jsonl"
    candidate_path = PROJECT_ROOT / "eval" / "eval_candidates.jsonl"
    if args.write_large_files:
        _write_jsonl(corpus_path, corpus.documents.values())
        _write_jsonl(dev_path, dev_cases)
    _write_jsonl(candidate_path, candidates)
    report["large_outputs_deferred"] = not args.write_large_files
    report["outputs"] = {
        "corpus_written": args.write_large_files,
        "retrieval_dev_written": args.write_large_files,
        "eval_candidates_written": True,
    }
    report_path = PROJECT_ROOT / "reports" / "corpus_audit.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "seed": args.seed,
        "retrieval_dev": report["retrieval_dev_count"],
        "eval_candidates": report["eval_candidate_count"],
        "corpus": report["corpus"], "evidence_coverage": report["evidence_coverage"],
        "large_outputs_deferred": not args.write_large_files,
    }, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

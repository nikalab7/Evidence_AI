"""Compare paired, independently recorded Gemini thinking experiments.

Read-only: never makes model calls, touches the database, or changes historical reports.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def read_rows(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    if not path.exists():
        raise FileNotFoundError(path)
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{number}: expected JSON object")
        if row.get("category") != "multi_hop" or row.get("execution_mode") != "live":
            continue
        case_id, mode = row.get("case_id"), row.get("retrieval_mode")
        if not isinstance(case_id, str) or not isinstance(mode, str):
            raise ValueError(f"{path}:{number}: missing case ID or retrieval mode")
        key = (case_id, mode)
        if key in rows:
            raise ValueError(f"{path}: duplicate multi-hop result: {key}")
        rows[key] = row
    return rows


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [float(r["latency_seconds"]) for r in rows
                 if isinstance(r.get("latency_seconds"), (float, int))]
    total_drafts = sum(r.get("draft_citation_count") or 0 for r in rows)
    total_valid = sum(r.get("verified_citation_count") or 0 for r in rows)
    return {
        "paired_cases": len(rows),
        "correct": sum(r.get("answer_correctness") is True for r in rows),
        "accuracy": round(sum(r.get("answer_correctness") is True for r in rows) / len(rows), 4),
        "errors": sum(r.get("error_type") is not None for r in rows),
        "cited_quotes_verified": total_valid,
        "draft_quotes": total_drafts,
        "citation_validity": round(total_valid / total_drafts, 4) if total_drafts else None,
        "gemini_http_requests": sum(r.get("api_request_count") or 0 for r in rows),
        "tool_calls": sum(r.get("tool_call_count") or 0 for r in rows),
        "median_latency_seconds": round(statistics.median(latencies), 3) if latencies else None,
    }


def compare(a: dict[tuple[str, str], dict[str, Any]],
            b: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    common = sorted(a.keys() & b.keys())
    if not common:
        raise ValueError("no paired multi-hop cases (or result files are empty)")
    for attr in ("dataset_sha256", "model"):
        values = {row.get(attr) for row in [*(a[k] for k in common), *(b[k] for k in common)]}
        if len(values) != 1 or None in values:
            raise ValueError(f"paired results have mismatched {attr}; cannot compare")
    changes = []
    for key in common:
        old, new = a[key], b[key]
        if (old.get("answer_correctness"), old.get("predicted_status"), old.get("error_type")) != (
            new.get("answer_correctness"), new.get("predicted_status"), new.get("error_type")
        ):
            changes.append({
                "case_id": key[0],
                "question": old.get("question"),
                "baseline_correct": old.get("answer_correctness"),
                "medium_correct": new.get("answer_correctness"),
                "baseline_status": old.get("predicted_status"),
                "medium_status": new.get("predicted_status"),
                "baseline_answer": old.get("predicted_answer"),
                "medium_answer": new.get("predicted_answer"),
            })
    baseline = _summary([a[k] for k in common])
    medium = _summary([b[k] for k in common])
    return {
        "paired_dataset_sha256": a[common[0]].get("dataset_sha256"),
        "model": a[common[0]].get("model"),
        "matched_multi_hop_cases": len(common),
        "unpaired_baseline": len(a.keys() - b.keys()),
        "unpaired_medium": len(b.keys() - a.keys()),
        "baseline": baseline,
        "medium": medium,
        "correctness_delta": medium["correct"] - baseline["correct"],
        "case_changes": changes,
        "note": "Observational A/B: reruns may vary; compare latency/cost as well as correctness.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path, help="minimal-thinking JSONL results")
    parser.add_argument("medium", type=Path, help="medium-thinking JSONL results")
    args = parser.parse_args()
    print(json.dumps(compare(read_rows(args.baseline), read_rows(args.medium)),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Fixed-seed, stratified selection of disjoint retrieval and candidate questions."""

from __future__ import annotations

import hashlib
import heapq
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from app.ingestion.corpus_core import (
    has_ten_context_paragraphs,
    question_stratum,
    supporting_evidence,
)


LEVELS = ("easy", "medium", "hard")
DEV_QUOTAS = {f"{kind}/{level}": quota for kind in ("bridge", "comparison")
              for level, quota in zip(LEVELS, (34, 33, 33))}
CANDIDATE_QUOTAS = {f"{kind}/{level}": quota for kind in ("bridge", "comparison")
                    for level, quota in zip(LEVELS, (7, 7, 6))}


def _score(seed: int, question_id: str) -> int:
    """Create a stable sampling rank without relying on Python's random version."""
    value = f"{seed}\0{question_id}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(value).digest(), "big")


def select_question_sets(
    rows: Iterable[Mapping[str, Any]], seed: int,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]], dict[str, Any]]:
    """Choose 200 retrieval questions and 40 separate candidates by type and level."""
    required = {key: DEV_QUOTAS[key] + CANDIDATE_QUOTAS[key] for key in DEV_QUOTAS}
    heaps: dict[str, list[tuple[int, str, int, Mapping[str, Any]]]] = defaultdict(list)
    counts, excluded, seen_ids = Counter(), Counter(), set()
    rows_scanned = 0
    for row in rows:
        rows_scanned += 1
        if rows_scanned % 10_000 == 0:
            message = f"Scanned {rows_scanned:,} train questions for stratified selection."
            print(message, file=sys.stderr)
        stratum = question_stratum(row)
        question_id = row.get("id")
        if stratum is None:
            excluded["unsupported_type_or_level"] += 1
            continue
        if not isinstance(question_id, str) or not question_id or question_id in seen_ids:
            excluded["missing_or_duplicate_question_id"] += 1
            continue
        seen_ids.add(question_id)
        if not has_ten_context_paragraphs(row):
            excluded["invalid_context_paragraph_count"] += 1
            continue
        if not row.get("question") or not row.get("answer") or not supporting_evidence(row):
            excluded["incomplete_question_or_support"] += 1
            continue
        counts[stratum] += 1
        score = _score(seed, question_id)
        heap = heaps[stratum]
        heapq.heappush(heap, (-score, question_id, rows_scanned, row))
        if len(heap) > required[stratum]:
            heapq.heappop(heap)

    dev_rows, candidate_rows = [], []
    for stratum in sorted(required):
        ranked = sorted(heaps[stratum], key=lambda item: (-item[0], item[1]))
        if len(ranked) < required[stratum]:
            raise ValueError(f"Not enough eligible {stratum} questions: {len(ranked)}")
        candidate_rows.extend(item[3] for item in ranked[:CANDIDATE_QUOTAS[stratum]])
        start = CANDIDATE_QUOTAS[stratum]
        dev_rows.extend(item[3] for item in ranked[start:start + DEV_QUOTAS[stratum]])
    dev_ids = {str(row["id"]) for row in dev_rows}
    candidate_ids = {str(row["id"]) for row in candidate_rows}
    if len(dev_rows) != 200 or len(candidate_rows) != 40 or dev_ids & candidate_ids:
        raise RuntimeError("Stratified question selection failed count or disjointness checks")
    stats = {
        "rows_scanned": rows_scanned,
        "unique_question_ids_seen": len(seen_ids),
        "eligible_question_counts_by_stratum": dict(sorted(counts.items())),
        "excluded_question_reasons": dict(sorted(excluded.items())),
        "selected_dev_counts_by_stratum": dict(sorted(DEV_QUOTAS.items())),
        "selected_candidate_counts_by_stratum": dict(sorted(CANDIDATE_QUOTAS.items())),
    }
    return dev_rows, candidate_rows, stats

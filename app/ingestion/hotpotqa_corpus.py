"""Reproducible local HotpotQA corpus construction and audit report."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from app.ingestion.corpus_core import context_paragraphs, coverage_report, evaluation_record
from app.ingestion.corpus_selection import select_question_sets
from app.ingestion.corpus_store import CorpusStore, SOURCE_URL
from app.ingestion.hotpotqa_audit import DATASET_CONFIG, DATASET_ID, DATASET_REVISION


CORPUS_TARGET = 50_000


def _open_train(load_dataset: Any, cache_dir: Path) -> Any:
    """Open only the pinned distractor train split as a streaming dataset."""
    return load_dataset(
        DATASET_ID, name=DATASET_CONFIG, split="train", revision=DATASET_REVISION,
        streaming=True, token=False, cache_dir=str(cache_dir),
    )


def _records_sha256(records: list[dict[str, Any]]) -> str:
    """Hash compact, sorted-key JSONL records with stable UTF-8 newlines."""
    digest = hashlib.sha256()
    for record in records:
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest.update((line + "\n").encode("utf-8"))
    return digest.hexdigest()


def build_hotpotqa_corpus(
    load_dataset: Any, datasets_version: str, seed: int, cache_dir: Path,
) -> tuple[dict[str, Any], CorpusStore, list[dict[str, Any]], list[dict[str, Any]]]:
    """Select evaluation sets, preserve their support first, then fill to 50,000."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    dev_rows, candidate_rows, selection = select_question_sets(
        _open_train(load_dataset, cache_dir), seed,
    )
    selected_ids = {str(row["id"]) for row in dev_rows + candidate_rows}
    corpus = CorpusStore(DATASET_REVISION)
    selected_rows = sorted(dev_rows + candidate_rows, key=lambda item: str(item["id"]))
    for row in selected_rows:
        for paragraph in context_paragraphs(row):
            corpus.add_paragraph(paragraph["title"], paragraph["sentences"])

    fill_questions = fill_questions_used = 0
    fill_stream = iter(_open_train(load_dataset, cache_dir))
    for fill_questions, row in enumerate(fill_stream, start=1):
        if fill_questions % 10_000 == 0:
            message = (f"Corpus fill scanned {fill_questions:,} questions; "
                       f"{len(corpus.documents):,} unique documents.")
            print(message, file=sys.stderr)
        if len(corpus.documents) >= CORPUS_TARGET or str(row.get("id", "")) in selected_ids:
            continue
        fill_questions_used += 1
        for paragraph in context_paragraphs(row):
            if len(corpus.documents) >= CORPUS_TARGET:
                break
            corpus.add_paragraph(paragraph["title"], paragraph["sentences"])
    close_stream = getattr(fill_stream, "close", None)
    if close_stream is not None:
        close_stream()

    dev_cases = [evaluation_record(row, DATASET_REVISION) for row in dev_rows]
    candidate_cases = [evaluation_record(row, DATASET_REVISION) for row in candidate_rows]
    coverage = {
        "retrieval_dev": coverage_report(dev_rows, corpus.documents.values()),
        "eval_candidates": coverage_report(candidate_rows, corpus.documents.values()),
        "combined": coverage_report(dev_rows + candidate_rows, corpus.documents.values()),
    }
    complete = coverage["combined"]
    passed = (
        len(corpus.documents) == CORPUS_TARGET
        and complete["supporting_title_coverage_percent"] == 100.0
        and complete["supporting_sentence_coverage_percent"] == 100.0
        and complete["questions_with_invalid_support"] == 0
    )
    report = {
        "status": "passed" if passed else "failed",
        "dataset": DATASET_ID, "dataset_config": DATASET_CONFIG,
        "source_url": SOURCE_URL, "license": "CC BY-SA 4.0",
        "dataset_revision": DATASET_REVISION, "datasets_library_version": datasets_version,
        "source_split": "train", "sampling_seed": seed,
        "selection_algorithm": (
            "lowest SHA-256(seed + NUL + question_id) score within each type/level stratum"
        ),
        "normalization": "Unicode NFKC, casefold, collapsed whitespace",
        "document_identity": "SHA-256 of normalized paragraph text; title is source metadata",
        "corpus_target": CORPUS_TARGET, "selected_context_paragraphs": len(selected_rows) * 10,
        "corpus": corpus.stats(),
        "corpus_jsonl_sha256": corpus.jsonl_sha256(),
        "retrieval_dev_count": len(dev_cases),
        "retrieval_dev_jsonl_sha256": _records_sha256(dev_cases),
        "eval_candidate_count": len(candidate_cases),
        "eval_candidates_jsonl_sha256": _records_sha256(candidate_cases),
        "candidate_pool_notice": (
            "40 candidates only; choose up to 25 multi-hop later and add separate 5 single-hop, "
            "8 unanswerable, and 7 conflicting cases."
        ),
        "question_sets_disjoint": not ({str(row["id"]) for row in dev_rows}
                                        & {str(row["id"]) for row in candidate_rows}),
        "selected_question_ids": {
            "retrieval_dev_csv": ",".join(str(row["id"]) for row in dev_rows),
            "eval_candidates_csv": ",".join(str(row["id"]) for row in candidate_rows),
        },
        "selection": selection, "evidence_coverage": coverage,
        "corpus_fill_questions_scanned": fill_questions,
        "corpus_fill_questions_used": fill_questions_used,
    }
    return report, corpus, dev_cases, candidate_cases

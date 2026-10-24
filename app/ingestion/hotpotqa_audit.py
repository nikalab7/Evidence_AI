"""Exact, reproducible uniqueness and supporting-evidence audit for HotpotQA."""

from __future__ import annotations

import hashlib
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from typing import Any


DATASET_ID = "hotpotqa/hotpot_qa"
DATASET_REVISION = "1908d6afbbead072334abe2965f91bd2709910ab"
DATASET_CONFIG = "distractor"
MINIMUM_UNIQUE_RECORDS = 50_000


def normalize_text(value: str) -> str:
    """Normalize Unicode, case, and whitespace for conservative exact matching."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _hash_parts(*parts: str) -> bytes:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.digest()


def _read_paragraphs(row: Mapping[str, Any]) -> tuple[list[tuple[str, list[str]]], bool]:
    context = row.get("context") or {}
    if not isinstance(context, Mapping):
        return [], True
    titles = context.get("title")
    sentences = context.get("sentences")
    if not isinstance(titles, list) or not isinstance(sentences, list):
        return [], True

    malformed = len(titles) != len(sentences)
    paragraphs: list[tuple[str, list[str]]] = []
    for title, paragraph_sentences in zip(titles, sentences):
        if not isinstance(title, str) or not isinstance(paragraph_sentences, list):
            malformed = True
            continue
        if not all(isinstance(sentence, str) for sentence in paragraph_sentences):
            malformed = True
            continue
        paragraphs.append((normalize_text(title), [
            normalize_text(sentence) for sentence in paragraph_sentences
        ]))
    return paragraphs, malformed


def _document_key(title: str, sentences: list[str]) -> bytes | None:
    body = " ".join(sentence for sentence in sentences if sentence)
    if not title or not body:
        return None
    return _hash_parts(title, body)


def _index_context(
    row: Mapping[str, Any],
    document_keys: set[bytes],
    sentence_index: set[bytes] | None,
    stats: Counter[str],
) -> dict[str, list[list[str]]]:
    paragraphs, malformed = _read_paragraphs(row)
    if malformed:
        stats["malformed_context_rows"] += 1
    context_by_title: dict[str, list[list[str]]] = {}
    for title, sentences in paragraphs:
        stats["context_paragraph_occurrences"] += 1
        context_by_title.setdefault(title, []).append(sentences)
        key = _document_key(title, sentences)
        if key is None:
            stats["empty_context_paragraphs"] += 1
            continue
        if key in document_keys:
            stats["duplicate_document_occurrences"] += 1
        else:
            document_keys.add(key)
        if sentence_index is not None:
            sentence_index.update(_hash_parts(title, sentence) for sentence in sentences if sentence)
    return context_by_title


def _find_supporting_sentence(
    title: str,
    sentence_id: int,
    context_by_title: Mapping[str, list[list[str]]],
) -> tuple[str | None, str | None]:
    matching_sentences = context_by_title.get(title, [])
    if not matching_sentences:
        return None, "support_title_missing_from_context"
    for sentences in matching_sentences:
        if 0 <= sentence_id < len(sentences) and sentences[sentence_id]:
            return sentences[sentence_id], None
    return None, "sentence_id_missing_or_empty"


def _record_invalid_evidence(
    question_id: str,
    reason: str,
    examples: list[dict[str, str]],
) -> None:
    if len(examples) < 10:
        examples.append({"question_id": question_id, "reason": reason})


def _scan_supporting_facts(
    row: Mapping[str, Any],
    question_id: str,
    context_by_title: Mapping[str, list[list[str]]],
    train_sentence_index: set[bytes],
    stats: Counter[str],
    type_counts: Counter[str],
    invalid_examples: list[dict[str, str]],
) -> None:
    question_type = str(row.get("type") or "unknown")
    question_level = str(row.get("level") or "unknown")
    type_counts[f"{question_type}/{question_level}"] += 1
    supporting_facts = row.get("supporting_facts") or {}
    if not isinstance(supporting_facts, Mapping):
        stats["malformed_supporting_fact_rows"] += 1
        return
    fact_titles = supporting_facts.get("title", [])
    sentence_ids = supporting_facts.get("sent_id", [])
    if not isinstance(fact_titles, list) or not isinstance(sentence_ids, list):
        stats["malformed_supporting_fact_rows"] += 1
        return
    if len(fact_titles) != len(sentence_ids):
        stats["malformed_supporting_fact_rows"] += 1
        return
    if not fact_titles:
        stats["empty_supporting_fact_rows"] += 1
        return

    stats["evaluation_questions_with_supporting_facts"] += 1
    all_valid, all_in_train = True, True
    for title, sentence_id in zip(fact_titles, sentence_ids):
        stats["supporting_fact_items"] += 1
        if not isinstance(title, str) or not isinstance(sentence_id, int):
            stats["invalid_supporting_fact_items"] += 1
            all_valid, all_in_train = False, False
            _record_invalid_evidence(question_id, "invalid_title_or_sentence_id_type", invalid_examples)
            continue
        normalized_title = normalize_text(title)
        sentence, reason = _find_supporting_sentence(
            normalized_title, sentence_id, context_by_title,
        )
        if sentence is None:
            stats["invalid_supporting_fact_items"] += 1
            all_valid, all_in_train = False, False
            _record_invalid_evidence(question_id, reason or "unknown", invalid_examples)
            continue
        stats["valid_supporting_fact_items_in_validation_context"] += 1
        if _hash_parts(normalized_title, sentence) in train_sentence_index:
            stats["supporting_fact_items_found_in_train_contexts"] += 1
        else:
            all_in_train = False

    if all_valid:
        stats["questions_with_valid_context_evidence"] += 1
    if all_valid and all_in_train:
        stats["questions_with_all_support_in_train_contexts"] += 1


def _split_summary(
    stats: Counter[str],
    document_keys: set[bytes],
    question_ids: set[str],
    type_counts: Counter[str],
    invalid_examples: list[dict[str, str]],
    *,
    is_validation: bool,
) -> dict[str, Any]:
    summary: dict[str, Any] = dict(stats)
    summary.update({
        "unique_question_ids": len(question_ids),
        "unique_document_records": len(document_keys),
    })
    if is_validation:
        valid_items = stats["valid_supporting_fact_items_in_validation_context"]
        total_items = stats["supporting_fact_items"]
        valid_questions = stats["questions_with_valid_context_evidence"]
        summary["supporting_fact_item_train_coverage"] = (
            stats["supporting_fact_items_found_in_train_contexts"] / valid_items
            if valid_items else None
        )
        summary["complete_question_train_coverage"] = (
            stats["questions_with_all_support_in_train_contexts"] / valid_questions
            if valid_questions else None
        )
        summary["validation_context_integrity"] = (
            valid_items / total_items if total_items else None
        )
        summary["type_level_counts"] = dict(sorted(type_counts.items()))
        summary["invalid_supporting_fact_examples"] = invalid_examples
    return summary


def _scan_split(
    rows: Iterable[Mapping[str, Any]],
    *,
    sentence_index: set[bytes] | None = None,
    train_sentence_index: set[bytes] | None = None,
    split_name: str = "split",
    progress: Callable[[str, int], None] | None = None,
) -> tuple[dict[str, Any], set[bytes], set[str]]:
    stats: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    document_keys: set[bytes] = set()
    question_ids: set[str] = set()
    invalid_examples: list[dict[str, str]] = []
    for row in rows:
        stats["question_rows"] += 1
        if progress is not None and stats["question_rows"] % 10_000 == 0:
            progress(split_name, stats["question_rows"])
        question_id = str(row.get("id") or "").strip()
        if not question_id:
            stats["missing_question_ids"] += 1
        elif question_id in question_ids:
            stats["duplicate_question_ids"] += 1
        else:
            question_ids.add(question_id)
        context_by_title = _index_context(row, document_keys, sentence_index, stats)
        if train_sentence_index is not None:
            _scan_supporting_facts(
                row, question_id, context_by_title, train_sentence_index,
                stats, type_counts, invalid_examples,
            )

    summary = _split_summary(
        stats, document_keys, question_ids, type_counts, invalid_examples,
        is_validation=train_sentence_index is not None,
    )
    return summary, document_keys, question_ids


def audit_hotpotqa_splits(
    train_rows: Iterable[Mapping[str, Any]],
    validation_rows: Iterable[Mapping[str, Any]],
    *,
    progress: Callable[[str, int], None] | None = None,
) -> dict[str, Any]:
    """Count exact title+paragraph records and check validation evidence coverage."""
    train_sentence_index: set[bytes] = set()
    train, train_documents, train_ids = _scan_split(
        train_rows, sentence_index=train_sentence_index,
        split_name="train", progress=progress,
    )
    validation, validation_documents, validation_ids = _scan_split(
        validation_rows, train_sentence_index=train_sentence_index,
        split_name="validation", progress=progress,
    )
    cross_split_duplicate_records = sum(key in train_documents for key in validation_documents)
    combined_unique_records = (
        train["unique_document_records"] + validation["unique_document_records"]
        - cross_split_duplicate_records
    )
    cross_split_duplicate_questions = len(train_ids.intersection(validation_ids))
    validation_question_count = validation.get("evaluation_questions_with_supporting_facts", 0)
    valid_validation_question_count = validation.get("questions_with_valid_context_evidence", 0)
    return {
        "dataset": DATASET_ID,
        "source_url": "https://huggingface.co/datasets/hotpotqa/hotpot_qa",
        "revision": DATASET_REVISION,
        "config": DATASET_CONFIG,
        "license": "CC BY-SA 4.0",
        "record_identity": "SHA-256 of normalized title and normalized joined paragraph text",
        "normalization": "Unicode NFKC, casefold, collapse whitespace",
        "deduplication_limit": "Exact normalized matches only; near-duplicate text variants are not merged.",
        "train": train,
        "validation": validation,
        "combined_context_corpus": {
            "unique_document_records": combined_unique_records,
            "duplicate_document_occurrences": (
                train.get("duplicate_document_occurrences", 0)
                + validation.get("duplicate_document_occurrences", 0)
                + cross_split_duplicate_records
            ),
            "duplicate_records_across_splits": cross_split_duplicate_records,
            "duplicate_question_ids_across_splits": cross_split_duplicate_questions,
            "meets_50000_unique_record_requirement": combined_unique_records >= MINIMUM_UNIQUE_RECORDS,
            "validation_support_item_presence": validation["validation_context_integrity"],
            "validation_questions_with_valid_context_support": (
                valid_validation_question_count / validation_question_count
                if validation_question_count else None
            ),
            "coverage_note": (
                "This corpus union includes validation contexts; source presence does not measure retrieval quality."
            ),
        },
        "evidence_limit": (
            "Exact title and sentence matching measures evidence presence, not factual entailment."
        ),
    }

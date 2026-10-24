"""Normalization, HotpotQA evidence extraction, and coverage checks."""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any


def normalize_text(value: str) -> str:
    """Apply Unicode NFKC, casefolding, and whitespace collapse before matching."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def content_hash(value: str) -> str:
    """Return SHA-256 of normalized paragraph text; titles do not affect identity."""
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def context_paragraphs(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Convert a HotpotQA context into valid title plus sentence paragraph records."""
    context = row.get("context") or {}
    if not isinstance(context, Mapping):
        return []
    titles, sentence_groups = context.get("title"), context.get("sentences")
    if not isinstance(titles, list) or not isinstance(sentence_groups, list):
        return []
    paragraphs = []
    for title, sentences in zip(titles, sentence_groups):
        if not isinstance(title, str) or not isinstance(sentences, list):
            continue
        if not all(isinstance(sentence, str) for sentence in sentences):
            continue
        text = " ".join(sentences).strip()
        if normalize_text(title) and normalize_text(text):
            paragraphs.append({"title": title, "sentences": sentences, "text": text})
    return paragraphs


def supporting_evidence(row: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    """Resolve every supporting title and sentence index against this question's context."""
    support = row.get("supporting_facts") or {}
    if not isinstance(support, Mapping):
        return None
    titles, indexes = support.get("title"), support.get("sent_id")
    if not isinstance(titles, list) or not isinstance(indexes, list) or len(titles) != len(indexes):
        return None
    by_title: dict[str, list[list[str]]] = {}
    for paragraph in context_paragraphs(row):
        by_title.setdefault(normalize_text(paragraph["title"]), []).append(paragraph["sentences"])
    evidence = []
    for title, sentence_id in zip(titles, indexes):
        if not isinstance(title, str) or not isinstance(sentence_id, int):
            return None
        paragraphs = by_title.get(normalize_text(title), [])
        sentence = next((paragraph[sentence_id] for paragraph in paragraphs
                         if 0 <= sentence_id < len(paragraph)
                         and normalize_text(paragraph[sentence_id])), None)
        if sentence is None:
            return None
        evidence.append({"title": title, "sentence_id": sentence_id, "sentence": sentence})
    return evidence or None


def question_stratum(row: Mapping[str, Any]) -> str | None:
    """Return one of the six requested question type and difficulty groups."""
    question_type, level = row.get("type"), row.get("level")
    if question_type not in ("bridge", "comparison") or level not in ("easy", "medium", "hard"):
        return None
    return f"{question_type}/{level}"


def has_ten_context_paragraphs(row: Mapping[str, Any]) -> bool:
    """Require all ten HotpotQA distractor contexts to be valid before selection."""
    context = row.get("context") or {}
    if not isinstance(context, Mapping):
        return False
    titles, sentence_groups = context.get("title"), context.get("sentences")
    return (isinstance(titles, list) and isinstance(sentence_groups, list)
            and len(titles) == len(sentence_groups) == 10
            and len(context_paragraphs(row)) == 10)


def evaluation_record(row: Mapping[str, Any], revision: str) -> dict[str, Any]:
    """Keep the question, answer, strata, stable source ID, and literal gold evidence."""
    return {
        "question_id": str(row["id"]), "question": row["question"], "answer": row["answer"],
        "type": row["type"], "level": row["level"], "supporting_evidence": supporting_evidence(row),
        "dataset": "hotpotqa/hotpot_qa", "config": "distractor", "split": "train",
        "revision": revision,
    }


def coverage_report(
    questions: Iterable[Mapping[str, Any]], documents: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Measure title and exact normalized support sentence presence in stored source variants."""
    titles_found: set[str] = set()
    title_sentences: set[tuple[str, str]] = set()
    for document in documents:
        for source in document.get("source_variants", []):
            title_key = normalize_text(source["title"])
            titles_found.add(title_key)
            title_sentences.update((title_key, normalize_text(sentence))
                                   for sentence in source["sentences"] if normalize_text(sentence))
    expected_titles: list[str] = []
    expected_sentences: list[tuple[str, str]] = []
    invalid_questions = 0
    for question in questions:
        facts = supporting_evidence(question)
        if not facts:
            invalid_questions += 1
            continue
        for fact in facts:
            title_key = normalize_text(fact["title"])
            expected_titles.append(title_key)
            expected_sentences.append((title_key, normalize_text(fact["sentence"])))
    title_hits = sum(item in titles_found for item in expected_titles)
    sentence_hits = sum(item in title_sentences for item in expected_sentences)
    total = len(expected_sentences)
    title_coverage = 100.0 * title_hits / len(expected_titles) if expected_titles else 0.0
    sentence_coverage = 100.0 * sentence_hits / total if total else 0.0
    if invalid_questions:
        title_coverage = sentence_coverage = 0.0
    return {
        "supporting_title_coverage_percent": title_coverage,
        "supporting_sentence_coverage_percent": sentence_coverage,
        "questions_with_invalid_support": invalid_questions,
        "supporting_title_references": len(expected_titles),
        "supporting_titles_found": title_hits,
        "supporting_sentence_references": total,
        "supporting_sentences_found": sentence_hits,
    }

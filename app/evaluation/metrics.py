"""Evidence-eligibility and ranking metrics for retrieval evaluation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.ingestion.corpus_core import normalize_text


def indexed_evidence_pairs(sources: Iterable[Mapping[str, Any]]) -> set[tuple[str, str]]:
    """Build normalized pairs, requiring the sentence in chunk text when supplied."""
    evidence: set[tuple[str, str]] = set()
    for source in sources:
        title = normalize_text(str(source.get("title_normalized") or source.get("title_alias") or ""))
        sentences = source.get("sentences") or []
        if not title or not isinstance(sentences, list):
            continue
        chunk_text = source.get("chunk_text")
        normalized_chunks = [normalize_text(chunk_text)] if isinstance(chunk_text, str) else None
        evidence.update(
            (title, normalize_text(sentence))
            for sentence in sentences
            if (isinstance(sentence, str) and normalize_text(sentence)
                and (normalized_chunks is None or any(
                    normalize_text(sentence) in chunk for chunk in normalized_chunks
                )))
        )
    return evidence


def has_complete_supporting_evidence(
    question: Mapping[str, Any], evidence_pairs: set[tuple[str, str]],
) -> bool:
    """Require every supporting title and exact normalized sentence to be indexed."""
    facts = question.get("supporting_evidence")
    if not isinstance(facts, list) or not facts:
        return False
    for fact in facts:
        if not isinstance(fact, Mapping):
            return False
        title, sentence = fact.get("title"), fact.get("sentence")
        if not isinstance(title, str) or not isinstance(sentence, str):
            return False
        if (normalize_text(title), normalize_text(sentence)) not in evidence_pairs:
            return False
    return True


def select_eligible_questions(
    questions: Sequence[Mapping[str, Any]], evidence_pairs: set[tuple[str, str]],
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Split evaluation cases so missing corpus evidence is not scored as a miss."""
    eligible, excluded = [], []
    for question in questions:
        destination = eligible if has_complete_supporting_evidence(question, evidence_pairs) else excluded
        destination.append(question)
    return eligible, excluded


def _hit_titles(hit: Mapping[str, Any]) -> set[str]:
    titles = {normalize_text(title) for title in hit.get("titles", []) if isinstance(title, str)}
    for source in hit.get("sources", []):
        if isinstance(source, Mapping) and isinstance(source.get("title_alias"), str):
            titles.add(normalize_text(source["title_alias"]))
    if isinstance(hit.get("title"), str):
        titles.add(normalize_text(hit["title"]))
    return {title for title in titles if title}


def score_question(
    question: Mapping[str, Any], ranked_hits: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    """Compute title-level Recall@5/10 and reciprocal rank for one question."""
    facts = question.get("supporting_evidence") or []
    gold_titles = {
        normalize_text(fact["title"])
        for fact in facts
        if isinstance(fact, Mapping) and isinstance(fact.get("title"), str)
    }
    if not gold_titles:
        raise ValueError("question has no valid supporting titles")

    ranked_title_sets = [_hit_titles(hit) for hit in ranked_hits]
    metrics: dict[str, float] = {}
    for k in (5, 10):
        retrieved = set().union(*ranked_title_sets[:k]) if ranked_title_sets[:k] else set()
        metrics[f"recall@{k}"] = len(gold_titles & retrieved) / len(gold_titles)
    first_relevant_rank = next(
        (rank for rank, titles in enumerate(ranked_title_sets, start=1) if gold_titles & titles),
        None,
    )
    metrics["mrr"] = 1 / first_relevant_rank if first_relevant_rank else 0.0
    return metrics


def aggregate_retrieval_metrics(
    questions: Sequence[Mapping[str, Any]],
    results_by_question: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Average ranking metrics over the caller-provided eligible question set."""
    if not questions:
        raise ValueError("cannot calculate retrieval metrics without eligible questions")
    per_question = []
    for question in questions:
        question_id = question.get("question_id")
        if not isinstance(question_id, str):
            raise ValueError("evaluation question is missing a stable question_id")
        per_question.append(score_question(question, results_by_question.get(question_id, [])))
    keys = ("recall@5", "recall@10", "mrr")
    return {
        "question_count": len(per_question),
        **{key: sum(row[key] for row in per_question) / len(per_question) for key in keys},
    }

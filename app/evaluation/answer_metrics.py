"""Deterministic answer, citation, and retrieved-evidence scoring helpers."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

from app.ingestion.corpus_core import normalize_text


def answer_tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)


def exact_match(expected: str, predicted: str) -> bool:
    return answer_tokens(expected) == answer_tokens(predicted)


def answer_span_match(expected: str, predicted: str) -> bool:
    """Check whether every gold answer token occurs contiguously in a claim."""
    expected_tokens, predicted_tokens = answer_tokens(expected), answer_tokens(predicted)
    if not expected_tokens or len(expected_tokens) > len(predicted_tokens):
        return False
    width = len(expected_tokens)
    return any(predicted_tokens[start:start + width] == expected_tokens
               for start in range(len(predicted_tokens) - width + 1))


def central_claim_text(result: Mapping[str, Any]) -> str:
    central_id = result.get("central_claim_id")
    for claim in result.get("claims", []):
        if isinstance(claim, Mapping) and claim.get("claim_id") == central_id:
            text = claim.get("text")
            return text if isinstance(text, str) else ""
    return ""


def evidence_coverage(
    supporting_evidence: Sequence[Mapping[str, Any]],
    retrieval_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if not supporting_evidence:
        return None
    found_pairs: list[dict[str, Any]] = []
    missing_pairs: list[dict[str, Any]] = []
    for fact in supporting_evidence:
        title = fact.get("title")
        sentence = fact.get("sentence")
        if not isinstance(title, str) or not isinstance(sentence, str):
            missing_pairs.append({"title": title, "reason": "invalid_gold_evidence"})
            continue
        expected_title, expected_sentence = normalize_text(title), normalize_text(sentence)
        matched = False
        for hit in retrieval_results:
            titles = hit.get("titles") or []
            if isinstance(hit.get("title"), str):
                titles = [*titles, hit["title"]]
            text = hit.get("evidence_text", "")
            if (expected_title in {normalize_text(value) for value in titles if isinstance(value, str)}
                    and isinstance(text, str)
                    and expected_sentence in normalize_text(text)):
                matched = True
                break
        target = found_pairs if matched else missing_pairs
        target.append({"title": title, "sentence_sha256": hashlib.sha256(
            sentence.encode("utf-8")).hexdigest()})
    total = len(found_pairs) + len(missing_pairs)
    return {
        "support_references": total,
        "support_references_retrieved": len(found_pairs),
        "coverage": len(found_pairs) / total if total else 0.0,
        "missing_support": missing_pairs,
    }


def case_quality(case: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    expected_status = case.get("expected_status")
    predicted_status = result.get("status")
    expected_answer = case.get("gold_answer")
    predicted_claim = central_claim_text(result)
    answerable = expected_status == "answered"
    span = (answer_span_match(expected_answer, predicted_claim)
            if answerable and isinstance(expected_answer, str) else None)
    em = (exact_match(expected_answer, predicted_claim)
          if answerable and isinstance(expected_answer, str) else None)
    correct = (
        predicted_status == "answered" and span is True
        if answerable else predicted_status == expected_status
    )
    evidence = result.get("trace", {}).get("evidence_diagnostic", {})
    generated_citations = evidence.get("draft_citation_count", 0)
    verified_citations = evidence.get("verified_citation_count", 0)
    citation_rate = (
        verified_citations / generated_citations if generated_citations else None
    )
    citations_valid = (
        citation_rate == 1.0 and evidence.get("rejected_claim_count", 0) == 0
        if generated_citations else None
    )
    return {
        "answer_correctness": bool(correct),
        "answer_span_match": span,
        "exact_match": em,
        "predicted_status": predicted_status,
        "citation_validity": citation_rate,
        "all_draft_citations_valid": citations_valid,
        "draft_citation_count": generated_citations,
        "verified_citation_count": verified_citations,
        "evidence_diagnostic": evidence.get("outcome"),
    }

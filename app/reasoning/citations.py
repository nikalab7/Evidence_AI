"""Two-level citation checks; quote presence is not a factual entailment test."""

from collections.abc import Mapping
from typing import Any

from app.reasoning.abstention import INSUFFICIENT_EVIDENCE_ANSWER
from app.reasoning.contradictions import verified_conflict_groups


def normalize_whitespace(text: str) -> str:
    """Collapse whitespace only; preserve case, punctuation, and Unicode text."""
    return " ".join(text.split())


def reconstruct_chunk_text(source: Mapping[str, Any]) -> str:
    """Slice canonical document text using PostgreSQL's half-open char offsets."""
    text = source.get("full_text")
    start, end = source.get("start_char"), source.get("end_char")
    if (not isinstance(text, str) or type(start) is not int or type(end) is not int
            or start < 0 or end <= start or end > len(text)):
        raise ValueError("invalid offset-based citation source")
    return text[start:end]


def validate_final_response(
    draft: Mapping[str, Any], retrieved: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Keep only claims whose chunk IDs and exact quotes match retrieved evidence."""
    if not isinstance(draft, Mapping) or set(draft) - {
        "central_claim_id", "claims", "conflict_groups",
    }:
        return _abstain([], [])
    claims = draft.get("claims")
    if not isinstance(claims, list):
        return _abstain([], [])

    verified: list[dict[str, Any]] = []
    verified_ids: set[str] = set()
    dropped: list[str] = []
    for claim in claims:
        claim_id = claim.get("claim_id") if isinstance(claim, Mapping) else None
        result = _validate_claim(claim, retrieved)
        if result is None or claim_id in verified_ids:
            if isinstance(claim_id, str):
                dropped.append(claim_id)
            continue
        verified.append(result)
        verified_ids.add(claim_id)

    central_id = draft.get("central_claim_id")
    if not isinstance(central_id, str) or central_id not in verified_ids:
        return _abstain(verified, dropped, central_id if isinstance(central_id, str) else None)

    groups = verified_conflict_groups(draft.get("conflict_groups"), verified_ids)
    status = "conflicting" if groups else "answered"
    answer = "The retrieved sources conflict on this point. " if groups else ""
    answer += " ".join(item["text"] for item in verified)
    return {
        "status": status, "answer": answer, "claims": verified,
        "central_claim_id": central_id, "conflict_groups": groups,
        "dropped_claim_ids": dropped,
    }


def _validate_claim(claim: Any, retrieved: Mapping[str, Mapping[str, Any]]) -> dict[str, Any] | None:
    if (not isinstance(claim, Mapping) or set(claim) != {"claim_id", "text", "citations"}
            or not isinstance(claim.get("claim_id"), str) or not claim["claim_id"].strip()
            or not isinstance(claim.get("text"), str) or not claim["text"].strip()
            or not isinstance(claim.get("citations"), list) or not claim["citations"]):
        return None
    citations = []
    for citation in claim["citations"]:
        if (not isinstance(citation, Mapping) or set(citation) != {"chunk_id", "quote"}
                or not isinstance(citation["chunk_id"], str)
                or not isinstance(citation["quote"], str) or not citation["quote"].strip()):
            return None
        evidence = retrieved.get(citation["chunk_id"])
        if evidence is None:
            return None
        try:
            text = reconstruct_chunk_text(evidence["validation_source"])
        except (KeyError, TypeError, ValueError):
            return None
        if evidence.get("evidence_text") != text:
            return None
        if normalize_whitespace(citation["quote"]) not in normalize_whitespace(text):
            return None
        citations.append({
            "chunk_id": citation["chunk_id"], "quote": citation["quote"],
            "doc_id": evidence.get("doc_id"), "title": evidence.get("title"),
            "titles": list(evidence.get("titles") or []),
            "sources": list(evidence.get("sources") or []),
        })
    return {"claim_id": claim["claim_id"], "text": claim["text"], "citations": citations}


def _abstain(claims: list[dict[str, Any]], dropped: list[str], central_id: str | None = None) -> dict[str, Any]:
    return {
        "status": "insufficient", "answer": INSUFFICIENT_EVIDENCE_ANSWER,
        "claims": claims, "central_claim_id": central_id,
        "conflict_groups": [], "dropped_claim_ids": dropped,
    }

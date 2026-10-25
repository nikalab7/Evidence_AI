"""Two-level citation checks; quote presence is not a factual entailment test."""

from collections.abc import Mapping
from typing import Any

from app.reasoning.abstention import INSUFFICIENT_EVIDENCE_ANSWER
from app.reasoning.contradictions import verified_conflict_groups
from app.reasoning.citation_checks import check_citation, normalize_whitespace, reconstruct_chunk_text


def validate_final_response(
    draft: Mapping[str, Any], retrieved: Mapping[str, Mapping[str, Any]],
    *, diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep only claims whose chunk IDs and exact quotes match retrieved evidence."""
    checks: list[dict[str, Any]] = []
    if diagnostics is not None:
        diagnostics.update({"citation_checks": checks, "central_claim_state": "invalid_response"})
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
    for claim_index, claim in enumerate(claims):
        claim_id = claim.get("claim_id") if isinstance(claim, Mapping) else None
        result = _validate_claim(claim, retrieved, checks, claim_index)
        if result is None or claim_id in verified_ids:
            if isinstance(claim_id, str):
                dropped.append(claim_id)
            continue
        verified.append(result)
        verified_ids.add(claim_id)

    central_id = draft.get("central_claim_id")
    groups = verified_conflict_groups(draft.get("conflict_groups"), verified_ids)
    if diagnostics is not None:
        diagnostics.update({
            "central_claim_state": "verified" if isinstance(central_id, str) and central_id in verified_ids else (
                "empty" if central_id == "" else "unverified"),
            "reported_conflict_group_count": len(draft.get("conflict_groups", []))
            if isinstance(draft.get("conflict_groups"), list) else 0,
            "verified_conflict_group_count": len(groups),
        })
    # A source conflict has no resolved winner. An explicitly empty central ID
    # may represent that state only when the model supplied a fully cited group.
    # A nonempty missing/rejected central claim must still fail closed.
    unresolved_conflict = central_id == "" and bool(groups) and not dropped
    if unresolved_conflict:
        central_id = None
    elif not isinstance(central_id, str) or central_id not in verified_ids:
        return _abstain(verified, dropped, central_id if isinstance(central_id, str) else None)
    status = "conflicting" if groups else "answered"
    answer = "The retrieved sources conflict on this point. " if groups else ""
    answer += " ".join(item["text"] for item in verified)
    return {
        "status": status, "answer": answer, "claims": verified,
        "central_claim_id": central_id, "conflict_groups": groups,
        "dropped_claim_ids": dropped,
    }


def _validate_claim(claim: Any, retrieved: Mapping[str, Mapping[str, Any]],
                    checks: list[dict[str, Any]], claim_index: int) -> dict[str, Any] | None:
    if (not isinstance(claim, Mapping) or set(claim) != {"claim_id", "text", "citations"}
            or not isinstance(claim.get("claim_id"), str) or not claim["claim_id"].strip()
            or not isinstance(claim.get("text"), str) or not claim["text"].strip()
            or not isinstance(claim.get("citations"), list) or not claim["citations"]):
        return None
    citations = []
    for citation_index, citation in enumerate(claim["citations"]):
        enriched, outcome = check_citation(citation, retrieved)
        checks.append({"claim_index": claim_index, "citation_index": citation_index, "outcome": outcome})
        if enriched is not None:
            citations.append(enriched)
    if len(citations) != len(claim["citations"]):
        return None
    return {"claim_id": claim["claim_id"], "text": claim["text"], "citations": citations}


def _abstain(claims: list[dict[str, Any]], dropped: list[str], central_id: str | None = None) -> dict[str, Any]:
    return {
        "status": "insufficient", "answer": INSUFFICIENT_EVIDENCE_ANSWER,
        "claims": claims, "central_claim_id": central_id,
        "conflict_groups": [], "dropped_claim_ids": dropped,
    }

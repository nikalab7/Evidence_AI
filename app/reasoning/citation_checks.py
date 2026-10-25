"""Exact citation checks with content-free failure reasons for diagnostics."""

from collections.abc import Mapping
from typing import Any


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def reconstruct_chunk_text(source: Mapping[str, Any]) -> str:
    text = source.get("full_text")
    start, end = source.get("start_char"), source.get("end_char")
    if (not isinstance(text, str) or type(start) is not int or type(end) is not int
            or start < 0 or end <= start or end > len(text)):
        raise ValueError("invalid offset-based citation source")
    return text[start:end]


def check_citation(citation: Any, retrieved: Mapping[str, Mapping[str, Any]]) -> tuple[Any, str]:
    """Return an enriched citation only when every original exact check passes."""
    if (not isinstance(citation, Mapping) or set(citation) != {"chunk_id", "quote"}
            or not isinstance(citation.get("chunk_id"), str)
            or not isinstance(citation.get("quote"), str) or not citation["quote"].strip()):
        return None, "invalid_citation_shape"
    evidence = retrieved.get(citation["chunk_id"])
    if evidence is None:
        return None, "chunk_not_retrieved"
    try:
        text = reconstruct_chunk_text(evidence["validation_source"])
    except (KeyError, TypeError, ValueError, AttributeError):
        return None, "invalid_source_offsets"
    if evidence.get("evidence_text") != text:
        return None, "source_text_mismatch"
    if normalize_whitespace(citation["quote"]) not in normalize_whitespace(text):
        return None, "quote_not_verbatim"
    return {
        "chunk_id": citation["chunk_id"], "quote": citation["quote"],
        "doc_id": evidence.get("doc_id"), "title": evidence.get("title"),
        "titles": list(evidence.get("titles") or []),
        "sources": list(evidence.get("sources") or []),
    }, "verified"

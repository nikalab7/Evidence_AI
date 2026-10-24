"""Allowlisted database tools used by the bounded investigation loop."""

from time import perf_counter
from typing import Any

from app.db.queries import read_document_context
from app.retrieval.engine import search


SEARCH_TOOL = {
    "name": "search_evidence",
    "description": "Search indexed EvidenceAI chunks by a focused natural-language query.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {"type": "STRING", "description": "One focused evidence query."},
            "k": {"type": "INTEGER", "description": "Number of results, 1 through 8."},
            "filters": {
                "type": "OBJECT",
                "properties": {
                    "source_split": {"type": "STRING"},
                    "chunking_strategy": {"type": "STRING"},
                    "embedding_model": {"type": "STRING"},
                },
            },
        },
        "required": ["query"],
    },
}
GET_DOCUMENT_TOOL = {
    "name": "get_document",
    "description": "Read the full text of a document already found by search_evidence.",
    "parameters": {
        "type": "OBJECT",
        "properties": {"doc_id": {"type": "STRING"}},
        "required": ["doc_id"],
    },
}
TOOL_DECLARATIONS = [SEARCH_TOOL, GET_DOCUMENT_TOOL]
MAX_TOOL_QUERY_CHARS = 500
MAX_TOOL_K = 8
DEFAULT_TOOL_K = 5
MAX_PROMPT_CHUNK_CHARS = 1200


def execute_tool(
    conn: Any, embedding_model: Any, name: str, arguments: dict[str, Any], *,
    retrieved: dict[str, dict[str, Any]], filters: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute only declared read tools and return result plus sanitized timings."""
    started = perf_counter()
    if name == "search_evidence":
        result, timing = _search(conn, embedding_model, arguments, retrieved, filters)
    elif name == "get_document":
        result, timing = _get_document(conn, arguments, retrieved)
    else:
        result, timing = {"error": "unknown_tool"}, {}
    timing.update({"tool": name, "total_seconds": round(perf_counter() - started, 6)})
    return result, timing


def _search(conn: Any, model: Any, args: dict[str, Any], evidence: dict[str, dict[str, Any]],
            base_filters: dict[str, str] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    query, limit, filters = args.get("query"), args.get("k", DEFAULT_TOOL_K), args.get("filters", {})
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_TOOL_QUERY_CHARS:
        return {"error": "invalid_search_query"}, {}
    if type(limit) is not int or not 1 <= limit <= MAX_TOOL_K:
        return {"error": "invalid_result_limit"}, {}
    if not isinstance(filters, dict) or any(
        key not in {"source_split", "chunking_strategy", "embedding_model"}
        or not isinstance(value, str) or not value.strip()
        for key, value in filters.items()
    ):
        return {"error": "invalid_search_filters"}, {}
    timings: dict[str, float] = {}
    hits = search(
        conn, query, mode="hybrid", limit=limit, candidate_limit=20, model=model,
        filters={**(base_filters or {}), **filters}, timings=timings,
        include_evidence_text=True, include_validation_source=True,
    )
    results = []
    for hit in hits:
        full_text = hit.get("evidence_text", "")
        trusted_item = {
            "chunk_id": hit["chunk_id"], "doc_id": hit["doc_id"],
            "title": hit.get("title"), "titles": hit.get("titles", []),
            "sources": hit.get("sources", []), "evidence_text": full_text,
            "validation_source": hit.get("validation_source"),
        }
        evidence[hit["chunk_id"]] = trusted_item
        results.append({
            "chunk_id": hit["chunk_id"], "doc_id": hit["doc_id"],
            "title": hit.get("title"), "titles": hit.get("titles", []),
            "text": full_text[:MAX_PROMPT_CHUNK_CHARS],
            "text_truncated": len(full_text) > MAX_PROMPT_CHUNK_CHARS,
        })
    return {"query": query, "results": results}, {key: round(value, 6) for key, value in timings.items()}


def _get_document(conn: Any, args: dict[str, Any], evidence: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    doc_id = args.get("doc_id")
    allowed_ids = {item.get("doc_id") for item in evidence.values()}
    if not isinstance(doc_id, str) or doc_id not in allowed_ids:
        return {"error": "document_not_in_retrieved_evidence"}, {}
    started = perf_counter()
    document = read_document_context(conn, doc_id)
    elapsed = perf_counter() - started
    if document is None:
        return {"error": "document_not_found"}, {"database_sql_seconds": round(elapsed, 6)}
    return document, {"database_sql_seconds": round(elapsed, 6)}

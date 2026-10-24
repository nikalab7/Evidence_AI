"""Stable content, source, and chunk identifiers for corpus ingestion."""

from __future__ import annotations

import hashlib
import json

from app.ingestion.corpus_core import content_hash


def stable_document_id(text: str) -> str:
    """Use normalized paragraph content as the document's stable identity."""
    return content_hash(text)


def stable_source_id(
    doc_id: str,
    title: str,
    source: str,
    revision: str,
    split: str,
    sentences: list[str],
) -> str:
    """Hash one title and provenance variant without losing its sentence list."""
    payload = {
        "doc_id": doc_id,
        "title": title,
        "source": source,
        "revision": revision,
        "split": split,
        "sentences": sentences,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def stable_chunk_id(doc_id: str, strategy: str, position: int, text: str) -> str:
    """Make chunk identity deterministic for a document, strategy, and position."""
    if position < 0:
        raise ValueError("chunk position must be non-negative")
    value = f"{doc_id}\0{strategy}\0{position}\0{content_hash(text)}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

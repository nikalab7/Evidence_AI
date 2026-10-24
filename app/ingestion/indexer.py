"""Prepare corpus documents and local embeddings for database insertion."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from app.ingestion.chunkers import PARAGRAPH_STRATEGY, paragraph_chunks
from app.ingestion.corpus_core import content_hash, normalize_text
from app.ingestion.deduplication import stable_chunk_id, stable_document_id, stable_source_id


EXPECTED_DIMENSIONS = 384


def prepare_document(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a corpus row and retain text, metadata, aliases, and chunk positions."""
    if not isinstance(record, Mapping):
        raise TypeError("corpus document must be an object")
    text = record.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("corpus document must have non-empty text")
    doc_id = record.get("doc_id")
    digest = stable_document_id(text)
    if doc_id != digest or record.get("content_hash") != digest:
        raise ValueError("corpus document ID does not match its normalized content hash")

    source = record.get("source")
    revision = record.get("source_revision")
    split = record.get("source_split")
    if not all(isinstance(value, str) and value for value in (source, revision, split)):
        raise ValueError("corpus document is missing source provenance")
    variants = record.get("source_variants")
    if not isinstance(variants, list) or not variants:
        raise ValueError("corpus document must include at least one source title alias")

    sources = []
    for variant in variants:
        if not isinstance(variant, Mapping):
            raise ValueError("source variants must be objects")
        title, sentences = variant.get("title"), variant.get("sentences")
        if (not isinstance(title, str) or not title.strip() or not isinstance(sentences, list)
                or not sentences or not all(isinstance(sentence, str) for sentence in sentences)):
            raise ValueError("source variant must include a title and sentence list")
        sources.append({
            "source_id": stable_source_id(doc_id, title, source, revision, split, sentences),
            "doc_id": doc_id,
            "title_alias": title,
            "title_normalized": normalize_text(title),
            "source_url": source,
            "source_revision": revision,
            "source_split": split,
            "sentences": sentences,
        })

    redundant_metadata_fields = {
        "text", "doc_id", "content_hash", "source", "source_revision",
        "source_split", "source_variants", "title",
    }
    metadata = {
        key: value for key, value in record.items()
        if key not in redundant_metadata_fields
    }
    chunks = []
    search_from = 0
    for position, chunk_text in enumerate(paragraph_chunks(text)):
        start_char = text.find(chunk_text, search_from)
        if start_char < 0:
            raise ValueError("paragraph chunk cannot be located in canonical document text")
        end_char = start_char + len(chunk_text)
        chunks.append({
            "chunk_id": stable_chunk_id(doc_id, PARAGRAPH_STRATEGY, position, chunk_text),
            "doc_id": doc_id,
            "chunk_position": position,
            "chunking_strategy": PARAGRAPH_STRATEGY,
            "start_char": start_char,
            "end_char": end_char,
            "chunk_text": chunk_text,
            "embedding": None,
            "embedding_model": None,
        })
        search_from = end_char
    return {
        "doc_id": doc_id,
        "content_hash": digest,
        "full_text": text,
        "metadata": metadata,
        "sources": sources,
        "chunks": chunks,
    }


def embed_documents(
    documents: Sequence[dict[str, Any]], model: Any, model_name: str, batch_size: int = 25,
) -> None:
    """Embed every prepared chunk locally and validate its 384 finite dimensions."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    chunks = [chunk for document in documents for chunk in document["chunks"]]
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start:start + batch_size]
        vectors = list(model.passage_embed([chunk["chunk_text"] for chunk in batch]))
        if len(vectors) != len(batch):
            raise ValueError("embedding model returned an unexpected number of vectors")
        for chunk, vector in zip(batch, vectors):
            values = [float(value) for value in vector]
            if len(values) != EXPECTED_DIMENSIONS or not all(math.isfinite(value) for value in values):
                raise ValueError(f"embedding must contain {EXPECTED_DIMENSIONS} finite values")
            chunk["embedding"] = values
            chunk["embedding_model"] = model_name

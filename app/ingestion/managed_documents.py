"""Index owner uploads through the existing content-addressed schema."""

from __future__ import annotations

from collections.abc import Mapping
import os
import unicodedata
from typing import Any
from uuid import UUID, uuid4

from app.db.connection import connect_database
from app.db.managed_uploads import (
    ConcurrentUploadUpdateError,
    ManagedUpload,
    UploadConflictError,
    UploadNotFoundError,
    delete_managed_upload,
    document_collision_kind,
    get_managed_upload,
    insert_managed_upload,
    list_managed_uploads,
    replace_managed_upload,
)
from app.embedding_smoke import MODEL_NAME
from app.ingestion.chunkers import PARAGRAPH_STRATEGY
from app.ingestion.deduplication import stable_document_id
from app.ingestion.indexer import embed_documents, prepare_document
from app.ingestion.parsers import (
    MAX_TITLE_CHARS,
    ParsedDocument,
    parse_uploaded_document,
    safe_original_filename,
)


SUPPORTED_CHUNKING_STRATEGIES = frozenset({PARAGRAPH_STRATEGY, "fixed_overlap"})
UPLOAD_SOURCE_REVISION = "managed-upload-v1"
UPLOAD_SOURCE_SPLIT = "managed_upload"
MAX_MANAGED_UPLOAD_CHUNKS = 250
MAX_PARAGRAPH_CHUNK_CHARS = 1_000


class UploadInputError(ValueError):
    """An owner supplied a title or strategy outside the supported limits."""


def parse_upload(filename: str | None, content: bytes) -> ParsedDocument:
    return parse_uploaded_document(filename, content)


def clean_upload_title(title: str | None, parsed_title: str) -> str:
    """Validate an optional owner title, falling back to parser metadata."""
    if title is None or not title.strip():
        return parsed_title
    cleaned = " ".join(title.split())
    if (not cleaned or len(cleaned) > MAX_TITLE_CHARS
            or any(unicodedata.category(char).startswith("C") for char in cleaned)):
        raise UploadInputError(f"title must contain 1-{MAX_TITLE_CHARS} printable characters")
    return cleaned


def list_uploads(*, limit: int = 50, offset: int = 0) -> list[ManagedUpload]:
    with connect_database() as conn:
        return list_managed_uploads(conn, limit=limit, offset=offset)


def inspect_upload(upload_id: UUID) -> ManagedUpload | None:
    with connect_database() as conn:
        return get_managed_upload(conn, upload_id)


def create_upload(
    *,
    filename: str | None,
    content: bytes,
    title: str | None,
    chunking_strategy: str,
    model: Any,
) -> ManagedUpload:
    parsed = parse_upload(filename, content)
    resolved_title = clean_upload_title(title, parsed.title)
    strategy = _validate_strategy(chunking_strategy)
    upload_id = uuid4()
    doc_id = stable_document_id(parsed.text)

    if _collision(doc_id):
        raise UploadConflictError(
            "Identical content already exists in the indexed library; no rows were changed."
        )

    document = _prepare_upload(
        upload_id=upload_id, title=resolved_title,
        chunking_strategy=strategy,
        text=parsed.text, model=model,
    )
    upload = _upload_row(
        upload_id=upload_id, document=document, parsed=parsed,
        original_filename=_safe_name(filename), title=resolved_title,
        strategy=strategy,
    )
    with connect_database() as conn:
        if not insert_managed_upload(conn, document, upload):
            raise UploadConflictError(
                "Identical content already exists in the indexed library; no rows were changed."
            )
        result = get_managed_upload(conn, upload_id)
    if result is None:
        raise RuntimeError("new managed upload could not be reloaded")
    return result


def replace_upload(
    *,
    upload_id: UUID,
    filename: str | None,
    content: bytes,
    title: str | None,
    chunking_strategy: str,
    model: Any,
) -> ManagedUpload:
    parsed = parse_upload(filename, content)
    resolved_title = clean_upload_title(title, parsed.title)
    strategy = _validate_strategy(chunking_strategy)
    original_filename = _safe_name(filename)

    current = inspect_upload(upload_id)
    if current is None:
        raise UploadNotFoundError("managed upload does not exist")
    new_doc_id = stable_document_id(parsed.text)
    if new_doc_id != current["doc_id"] and _collision(new_doc_id):
        raise UploadConflictError(
            "Replacement content already exists in the indexed library; the current upload was left unchanged."
        )

    needs_reindex = (
        new_doc_id != current["doc_id"] or strategy != current["chunking_strategy"]
    )
    if needs_reindex:
        canonical_text = parsed.text if new_doc_id != current["doc_id"] else current["text"]
        document = _prepare_upload(
            upload_id=upload_id, title=resolved_title,
            chunking_strategy=strategy,
            text=canonical_text, model=model,
        )
    else:
        document = _prepare_upload_metadata_only(
            upload_id=upload_id, title=resolved_title, text=current["text"],
        )

    upload = _upload_row(
        upload_id=upload_id, document=document, parsed=parsed,
        original_filename=original_filename, title=resolved_title,
        strategy=strategy,
    )
    with connect_database() as conn:
        return replace_managed_upload(
            conn,
            upload_id=upload_id,
            expected_doc_id=current["doc_id"],
            expected_source_id=current["source_id"],
            expected_row_version=current["row_version"],
            document=document,
            upload=upload,
        )


def remove_upload(upload_id: UUID) -> bool:
    with connect_database() as conn:
        return delete_managed_upload(conn, upload_id)


def _collision(doc_id: str) -> str | None:
    with connect_database() as conn:
        return document_collision_kind(conn, doc_id)


def _validate_strategy(strategy: str) -> str:
    if strategy not in SUPPORTED_CHUNKING_STRATEGIES:
        raise UploadInputError("unsupported chunking strategy")
    return strategy


def _safe_name(filename: str | None) -> str:
    return safe_original_filename(filename)


def _source_record(upload_id: UUID, doc_id: str, title: str) -> dict[str, Any]:
    return {
        "title": title,
        "sentences": [],
        "_doc_id": doc_id,
        "_source": f"upload://{upload_id}",
        "_source_revision": UPLOAD_SOURCE_REVISION,
        "_source_split": UPLOAD_SOURCE_SPLIT,
    }


def _prepare_upload(
    *,
    upload_id: UUID,
    title: str,
    chunking_strategy: str,
    text: str,
    model: Any,
) -> dict[str, Any]:
    document = _prepare_upload_metadata_only(
        upload_id=upload_id, title=title, text=text,
        chunking_strategy=chunking_strategy,
    )
    model_name = os.getenv("FASTEMBED_MODEL", MODEL_NAME).strip() or MODEL_NAME
    embed_documents([document], model, model_name)
    return document


def _prepare_upload_metadata_only(
    *,
    upload_id: UUID,
    title: str,
    text: str,
    chunking_strategy: str = PARAGRAPH_STRATEGY,
) -> dict[str, Any]:
    digest = stable_document_id(text)
    source = _source_record(upload_id, digest, title)
    record: dict[str, Any] = {
        "doc_id": digest,
        "content_hash": digest,
        "text": text,
        "title": title,
        "source": source["_source"],
        "source_revision": source["_source_revision"],
        "source_split": source["_source_split"],
        "source_variants": [{"title": title, "sentences": []}],
    }
    document = prepare_document(
        record,
        chunking_strategy=chunking_strategy,
        allow_empty_source_sentences=True,
        max_paragraph_chars=MAX_PARAGRAPH_CHUNK_CHARS,
    )
    if len(document["chunks"]) > MAX_MANAGED_UPLOAD_CHUNKS:
        raise UploadInputError(
            f"The document needs more than {MAX_MANAGED_UPLOAD_CHUNKS} chunks; "
            "shorten it or choose a different file."
        )
    document["sources"][0]["source_url"] = source["_source"]
    return document


def _upload_row(
    *,
    upload_id: UUID,
    document: Mapping[str, Any],
    parsed: ParsedDocument,
    original_filename: str,
    title: str,
    strategy: str,
) -> dict[str, Any]:
    return {
        "upload_id": upload_id,
        "doc_id": document["doc_id"],
        "source_id": document["sources"][0]["source_id"],
        "original_filename": original_filename,
        "file_format": parsed.file_format,
        "title": title,
        "file_size_bytes": parsed.file_size_bytes,
        "chunking_strategy": strategy,
        "parser_metadata": parsed.parser_metadata,
    }

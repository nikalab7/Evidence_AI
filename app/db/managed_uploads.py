"""Parameterized transactional CRUD for admin-managed uploaded documents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypedDict
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.db.queries import CHUNKS_UPSERT_SQL, SOURCES_UPSERT_SQL


class ManagedUpload(TypedDict, total=False):
    upload_id: str
    doc_id: str
    source_id: str
    original_filename: str
    file_format: str
    title: str
    file_size_bytes: int
    chunking_strategy: str
    parser_metadata: dict[str, Any]
    uploaded_at: Any
    updated_at: Any
    row_version: int
    source_url: str
    source_revision: str
    source_split: str
    source_sentences: list[str]
    text: str
    document_metadata: dict[str, Any]
    chunk_count: int
    text_chars: int


class UploadNotFoundError(LookupError):
    """No managed upload exists for the requested stable upload ID."""


class UploadConflictError(ValueError):
    """The requested content or operation would collide with existing data."""


class SharedDocumentError(UploadConflictError):
    """Refuse a strategy replacement that would modify shared corpus chunks."""


class ConcurrentUploadUpdateError(UploadConflictError):
    """The upload changed after the request read it; ask the owner to reload."""


DOCUMENT_INSERT_SQL = """
INSERT INTO public.documents (doc_id, content_hash, full_text, metadata)
VALUES (%s, %s, %s, %s)
ON CONFLICT (doc_id) DO NOTHING
RETURNING doc_id
"""

UPLOAD_INSERT_SQL = """
INSERT INTO public.managed_uploads (
    upload_id, doc_id, source_id, original_filename, file_format, title,
    file_size_bytes, chunking_strategy, parser_metadata
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

UPLOAD_SELECT_COLUMNS = """
m.upload_id::text, m.doc_id, m.source_id, m.original_filename, m.file_format,
m.title, m.file_size_bytes, m.chunking_strategy, m.parser_metadata,
m.uploaded_at, m.updated_at, m.row_version
"""


def document_collision_kind(conn: Connection, doc_id: str) -> str | None:
    """Distinguish existing managed content from protected pre-existing content."""
    row = conn.execute(
        """SELECT EXISTS (SELECT 1 FROM public.documents WHERE doc_id = %s),
                  EXISTS (SELECT 1 FROM public.managed_uploads WHERE doc_id = %s)""",
        (doc_id, doc_id),
    ).fetchone()
    if not row or not row[0]:
        return None
    return "managed" if row[1] else "protected"


def list_managed_uploads(
    conn: Connection, *, limit: int = 50, offset: int = 0,
) -> list[ManagedUpload]:
    """List only admin-managed documents; source corpus rows are never listed."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be non-negative")
    rows = conn.execute(
        f"""SELECT {UPLOAD_SELECT_COLUMNS}, char_length(d.full_text),
                     count(c.chunk_id)::integer, s.source_url,
                     s.source_revision, s.source_split, s.sentences
              FROM public.managed_uploads m
              JOIN public.documents d ON d.doc_id = m.doc_id
               JOIN public.document_sources s ON s.source_id = m.source_id
                                               AND s.doc_id = m.doc_id
              LEFT JOIN public.chunks c ON c.doc_id = m.doc_id
              GROUP BY m.upload_id, d.doc_id, s.source_id
              ORDER BY m.uploaded_at DESC, m.upload_id
              LIMIT %s OFFSET %s""",
        (limit, offset),
    ).fetchall()
    return [_map_upload(row, include_text=False, list_row=True) for row in rows]


def get_managed_upload(conn: Connection, upload_id: UUID) -> ManagedUpload | None:
    """Return one managed document and canonical text for authenticated inspection."""
    row = conn.execute(
        f"""SELECT {UPLOAD_SELECT_COLUMNS}, d.full_text, d.metadata,
                     (SELECT count(*)::integer FROM public.chunks c WHERE c.doc_id = m.doc_id),
                     s.source_url, s.source_revision, s.source_split, s.sentences
              FROM public.managed_uploads m
              JOIN public.documents d ON d.doc_id = m.doc_id
               JOIN public.document_sources s ON s.source_id = m.source_id
                                               AND s.doc_id = m.doc_id
              WHERE m.upload_id = %s""",
        (upload_id,),
    ).fetchone()
    return _map_upload(row, include_text=True, list_row=False) if row else None


def insert_managed_upload(
    conn: Connection,
    document: Mapping[str, Any],
    upload: Mapping[str, Any],
) -> bool:
    """Atomically insert canonical text, provenance, chunks, and its owner row.

    Returns false on a content-address collision without touching the existing
    document or its provenance. The caller may then report a safe duplicate.
    """
    with conn.transaction():
        if not _insert_document_content(conn, document):
            return False
        _insert_upload_row(conn, upload)
    return True


def replace_managed_upload(
    conn: Connection,
    *,
    upload_id: UUID,
    expected_doc_id: str,
    expected_source_id: str,
    expected_row_version: int,
    document: Mapping[str, Any],
    upload: Mapping[str, Any],
) -> ManagedUpload:
    """Replace upload metadata/content without mutating a content-addressed row."""
    with conn.transaction():
        current = _get_upload_for_update(conn, upload_id)
        if current is None:
            raise UploadNotFoundError("managed upload does not exist")
        if (current[1] != expected_doc_id or current[2] != expected_source_id
                or current[11] != expected_row_version):
            raise ConcurrentUploadUpdateError("the managed upload changed; reload and retry")

        old_doc_id, old_source_id = current[1], current[2]
        new_doc_id = document["doc_id"]
        new_source = document["sources"][0]
        new_source_id = new_source["source_id"]
        new_strategy = upload["chunking_strategy"]
        old_strategy = current[7]

        if new_doc_id != old_doc_id:
            if not _insert_document_content(conn, document):
                raise UploadConflictError(
                    "This content already exists in the indexed library; the existing document was left unchanged."
                )
        else:
            if new_strategy != old_strategy:
                other_sources = conn.execute(
                    """SELECT 1 FROM public.document_sources
                       WHERE doc_id = %s AND source_id <> %s LIMIT 1""",
                    (old_doc_id, old_source_id),
                ).fetchone()
                if other_sources:
                    raise SharedDocumentError(
                        "This document has other provenance records; its indexing cannot be replaced from the upload library."
                    )
                conn.execute("DELETE FROM public.chunks WHERE doc_id = %s", (old_doc_id,))
                _insert_chunk_rows(conn, document["chunks"])

            if new_source_id != old_source_id:
                _insert_source_rows(conn, document["sources"])

        conn.execute(
            """UPDATE public.managed_uploads
               SET doc_id = %s, source_id = %s, original_filename = %s,
                   file_format = %s, title = %s, file_size_bytes = %s,
                   chunking_strategy = %s, parser_metadata = %s,
                   updated_at = clock_timestamp(), row_version = row_version + 1
               WHERE upload_id = %s""",
            (
                new_doc_id, new_source_id, upload["original_filename"],
                upload["file_format"], upload["title"], upload["file_size_bytes"],
                new_strategy, Jsonb(upload["parser_metadata"]), upload_id,
            ),
        )

        if new_source_id != old_source_id:
            conn.execute(
                "DELETE FROM public.document_sources WHERE source_id = %s AND doc_id = %s",
                (old_source_id, old_doc_id),
            )
        if new_doc_id != old_doc_id:
            _delete_document_if_unreferenced(conn, old_doc_id)

    refreshed = get_managed_upload(conn, upload_id)
    if refreshed is None:
        raise RuntimeError("updated managed upload could not be reloaded")
    return refreshed


def delete_managed_upload(conn: Connection, upload_id: UUID) -> bool:
    """Delete only upload-owned provenance; retain any document still referenced."""
    with conn.transaction():
        current = _get_upload_for_update(conn, upload_id)
        if current is None:
            return False
        doc_id, source_id = current[1], current[2]
        conn.execute("DELETE FROM public.managed_uploads WHERE upload_id = %s", (upload_id,))
        conn.execute(
            "DELETE FROM public.document_sources WHERE source_id = %s AND doc_id = %s",
            (source_id, doc_id),
        )
        _delete_document_if_unreferenced(conn, doc_id)
    return True


def _insert_document_content(conn: Connection, document: Mapping[str, Any]) -> bool:
    row = conn.execute(
        DOCUMENT_INSERT_SQL,
        (document["doc_id"], document["content_hash"], document["full_text"],
         Jsonb(document["metadata"])),
    ).fetchone()
    if row is None:
        return False
    _insert_source_rows(conn, document["sources"])
    _insert_chunk_rows(conn, document["chunks"])
    return True


def _insert_source_rows(conn: Connection, sources: Sequence[Mapping[str, Any]]) -> None:
    if not sources:
        raise ValueError("managed upload must have title provenance")
    rows = [dict(source) for source in sources]
    inserted = {row[0] for row in conn.execute(
        SOURCES_UPSERT_SQL, (Jsonb(rows),),
    ).fetchall()}
    expected = {source["source_id"] for source in sources}
    if inserted != expected:
        raise RuntimeError("managed upload provenance could not be inserted atomically")


def _insert_chunk_rows(conn: Connection, chunks: Sequence[Mapping[str, Any]]) -> None:
    if not chunks:
        raise ValueError("managed upload must produce at least one chunk")
    if any(chunk.get("embedding") is None or chunk.get("embedding_model") is None for chunk in chunks):
        raise ValueError("all managed upload chunks must be embedded before insertion")
    rows = [{key: chunk[key] for key in (
        "chunk_id", "doc_id", "chunk_position", "chunking_strategy", "start_char",
        "end_char", "chunk_text", "embedding", "embedding_model",
    )} for chunk in chunks]
    inserted = {row[0] for row in conn.execute(CHUNKS_UPSERT_SQL, (Jsonb(rows),)).fetchall()}
    expected = {chunk["chunk_id"] for chunk in chunks}
    if inserted != expected:
        raise RuntimeError("managed upload chunks could not be inserted atomically")


def _insert_upload_row(conn: Connection, upload: Mapping[str, Any]) -> None:
    conn.execute(
        UPLOAD_INSERT_SQL,
        (
            upload["upload_id"], upload["doc_id"], upload["source_id"],
            upload["original_filename"], upload["file_format"], upload["title"],
            upload["file_size_bytes"], upload["chunking_strategy"],
            Jsonb(upload["parser_metadata"]),
        ),
    )


def _get_upload_for_update(conn: Connection, upload_id: UUID) -> tuple[Any, ...] | None:
    return conn.execute(
        f"""SELECT {UPLOAD_SELECT_COLUMNS}
            FROM public.managed_uploads m
            WHERE m.upload_id = %s FOR UPDATE""",
        (upload_id,),
    ).fetchone()


def _delete_document_if_unreferenced(conn: Connection, doc_id: str) -> None:
    conn.execute(
        """DELETE FROM public.documents d
           WHERE d.doc_id = %s
             AND NOT EXISTS (SELECT 1 FROM public.document_sources s WHERE s.doc_id = d.doc_id)
             AND NOT EXISTS (SELECT 1 FROM public.managed_uploads m WHERE m.doc_id = d.doc_id)""",
        (doc_id,),
    )


def _map_upload(row: tuple[Any, ...], *, include_text: bool, list_row: bool) -> ManagedUpload:
    result: ManagedUpload = {
        "upload_id": row[0], "doc_id": row[1], "source_id": row[2],
        "original_filename": row[3], "file_format": row[4], "title": row[5],
        "file_size_bytes": row[6], "chunking_strategy": row[7],
        "parser_metadata": row[8] or {}, "uploaded_at": row[9], "updated_at": row[10],
        "row_version": row[11],
    }
    if list_row:
        result["text_chars"] = row[12]
        result["chunk_count"] = row[13]
        result["source_url"] = row[14]
        result["source_revision"] = row[15]
        result["source_split"] = row[16]
        result["source_sentences"] = row[17] or []
    elif include_text:
        result["text"] = row[12]
        result["document_metadata"] = row[13] or {}
        result["chunk_count"] = row[14]
        result["source_url"] = row[15]
        result["source_revision"] = row[16]
        result["source_split"] = row[17]
        result["source_sentences"] = row[18] or []
    return result

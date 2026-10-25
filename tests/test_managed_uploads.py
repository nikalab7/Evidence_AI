from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.db.managed_uploads import (
    UploadConflictError,
    delete_managed_upload,
    insert_managed_upload,
    replace_managed_upload,
)
from app.ingestion.managed_documents import create_upload, replace_upload, remove_upload


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class MemoryDatabase:
    """Small transactional SQL fake used only to test ownership invariants."""

    def __init__(self):
        self.documents = {}
        self.sources = {}
        self.chunks = {}
        self.uploads = {}
        self.fail_chunk_insert = False
        self.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    @contextmanager
    def transaction(self):
        before = deepcopy((self.documents, self.sources, self.chunks, self.uploads, self.updated_at))
        try:
            yield
        except Exception:
            self.documents, self.sources, self.chunks, self.uploads, self.updated_at = before
            raise

    @staticmethod
    def _payload(value):
        return value.obj if hasattr(value, "obj") else value

    def execute(self, query, params=()):
        sql = " ".join(str(query).split())
        upper = sql.upper()
        if upper.startswith("INSERT INTO PUBLIC.DOCUMENTS"):
            doc_id, content_hash, full_text, metadata = params
            if doc_id in self.documents:
                return Result()
            self.documents[doc_id] = {
                "content_hash": content_hash, "full_text": full_text,
                "metadata": self._payload(metadata),
            }
            return Result([(doc_id,)])
        if upper.startswith("INSERT INTO PUBLIC.DOCUMENT_SOURCES"):
            rows = self._payload(params[0])
            inserted = []
            for row in rows:
                if row["source_id"] not in self.sources:
                    self.sources[row["source_id"]] = dict(row)
                    inserted.append((row["source_id"],))
            return Result(inserted)
        if upper.startswith("INSERT INTO PUBLIC.CHUNKS"):
            if self.fail_chunk_insert:
                raise RuntimeError("simulated insert failure")
            rows = self._payload(params[0])
            inserted = []
            for row in rows:
                if row["chunk_id"] not in self.chunks:
                    self.chunks[row["chunk_id"]] = dict(row)
                    inserted.append((row["chunk_id"],))
            return Result(inserted)
        if upper.startswith("INSERT INTO PUBLIC.MANAGED_UPLOADS"):
            (upload_id, doc_id, source_id, filename, file_format, title,
             size, strategy, parser_metadata) = params
            self.uploads[upload_id] = {
                "upload_id": upload_id, "doc_id": doc_id, "source_id": source_id,
                "original_filename": filename, "file_format": file_format,
                "title": title, "file_size_bytes": size,
                "chunking_strategy": strategy,
                "parser_metadata": self._payload(parser_metadata),
                "uploaded_at": self.updated_at, "updated_at": self.updated_at,
            }
            return Result()
        if "SELECT EXISTS (SELECT 1 FROM PUBLIC.DOCUMENTS" in upper:
            doc_id = params[0]
            return Result([(doc_id in self.documents, any(row["doc_id"] == doc_id
                                                           for row in self.uploads.values()))])
        if "FOR UPDATE" in upper and "FROM PUBLIC.MANAGED_UPLOADS M" in upper:
            row = self.uploads.get(params[0])
            return Result([self._base_tuple(row)] if row else [])
        if upper.startswith("SELECT M.UPLOAD_ID::TEXT") and "FROM PUBLIC.MANAGED_UPLOADS M" in upper:
            row = self.uploads.get(params[0])
            if row is None:
                return Result()
            source = self.sources[row["source_id"]]
            doc = self.documents[row["doc_id"]]
            chunks = [chunk for chunk in self.chunks.values() if chunk["doc_id"] == row["doc_id"]]
            if "CHAR_LENGTH(D.FULL_TEXT)" in upper:
                extra = (len(doc["full_text"]), len(chunks), source["source_url"],
                         source["source_revision"], source["source_split"], source["sentences"])
            else:
                extra = (doc["full_text"], doc["metadata"], len(chunks), source["source_url"],
                         source["source_revision"], source["source_split"], source["sentences"])
            return Result([self._base_tuple(row) + extra])
        if "SELECT 1 FROM PUBLIC.DOCUMENT_SOURCES" in upper and "SOURCE_ID <> %S" in upper:
            doc_id, source_id = params
            found = any(row["doc_id"] == doc_id and row["source_id"] != source_id
                        for row in self.sources.values())
            return Result([(1,)] if found else [])
        if upper.startswith("UPDATE PUBLIC.MANAGED_UPLOADS"):
            (doc_id, source_id, filename, file_format, title, size, strategy,
             parser_metadata, upload_id) = params
            row = self.uploads[upload_id]
            row.update(doc_id=doc_id, source_id=source_id, original_filename=filename,
                       file_format=file_format, title=title, file_size_bytes=size,
                       chunking_strategy=strategy, parser_metadata=self._payload(parser_metadata))
            self.updated_at = self.updated_at.replace(second=self.updated_at.second + 1)
            row["updated_at"] = self.updated_at
            return Result()
        if upper.startswith("DELETE FROM PUBLIC.CHUNKS WHERE DOC_ID"):
            doc_id = params[0]
            self.chunks = {key: row for key, row in self.chunks.items() if row["doc_id"] != doc_id}
            return Result()
        if upper.startswith("DELETE FROM PUBLIC.MANAGED_UPLOADS WHERE UPLOAD_ID"):
            self.uploads.pop(params[0], None)
            return Result()
        if upper.startswith("DELETE FROM PUBLIC.DOCUMENT_SOURCES WHERE SOURCE_ID"):
            source_id, doc_id = params
            row = self.sources.get(source_id)
            if row and row["doc_id"] == doc_id:
                self.sources.pop(source_id)
            return Result()
        if upper.startswith("DELETE FROM PUBLIC.DOCUMENTS D"):
            doc_id = params[0]
            has_sources = any(row["doc_id"] == doc_id for row in self.sources.values())
            has_uploads = any(row["doc_id"] == doc_id for row in self.uploads.values())
            if not has_sources and not has_uploads:
                self.documents.pop(doc_id, None)
                self.chunks = {key: row for key, row in self.chunks.items() if row["doc_id"] != doc_id}
            return Result()
        raise AssertionError(f"unexpected SQL in test fake: {sql[:80]}")

    @staticmethod
    def _base_tuple(row):
        return (
            str(row["upload_id"]), row["doc_id"], row["source_id"], row["original_filename"],
            row["file_format"], row["title"], row["file_size_bytes"],
            row["chunking_strategy"], row["parser_metadata"], row["uploaded_at"], row["updated_at"],
        )


class FakeEmbeddingModel:
    def passage_embed(self, texts):
        return [[0.1] * 384 for _ in texts]


def _save_service_db(monkeypatch, db):
    import app.ingestion.managed_documents as service
    monkeypatch.setattr(service, "connect_database", lambda: db)


def test_create_duplicate_replace_delete_and_corpus_ownership(monkeypatch):
    db = MemoryDatabase()
    _save_service_db(monkeypatch, db)
    created = create_upload(
        filename="one.txt", content=b"First canonical text.", title="First title",
        chunking_strategy="paragraph", model=FakeEmbeddingModel(),
    )
    original_doc_id = created["doc_id"]
    before = deepcopy((db.documents, db.sources, db.chunks, db.uploads))

    with pytest.raises(UploadConflictError):
        create_upload(
            filename="duplicate.txt", content=b"First canonical text.", title="Another title",
            chunking_strategy="paragraph", model=FakeEmbeddingModel(),
        )
    assert (db.documents, db.sources, db.chunks, db.uploads) == before

    # A later corpus alias makes the canonical document shared. Deleting the
    # upload must remove only its manager row and owned source.
    db.sources["corpus-source"] = {
        "source_id": "corpus-source", "doc_id": original_doc_id,
        "title_alias": "Original corpus title", "title_normalized": "original corpus title",
        "source_url": "https://example.test/corpus", "source_revision": "train-v1",
        "source_split": "train", "sentences": ["Evidence sentence."],
    }
    upload_id = UUID(created["upload_id"])
    assert remove_upload(upload_id) is True
    assert original_doc_id in db.documents
    assert "corpus-source" in db.sources
    assert any(chunk["doc_id"] == original_doc_id for chunk in db.chunks.values())
    assert not db.uploads


def test_replacement_uses_new_content_id_and_removes_unreferenced_old_content(monkeypatch):
    db = MemoryDatabase()
    _save_service_db(monkeypatch, db)
    created = create_upload(
        filename="one.txt", content=b"Old canonical content.", title="Old title",
        chunking_strategy="paragraph", model=FakeEmbeddingModel(),
    )
    old_doc_id = created["doc_id"]
    replaced = replace_upload(
        upload_id=UUID(created["upload_id"]), filename="two.txt",
        content="New canonical content with Unicode 🧭.".encode(), title="New title",
        chunking_strategy="fixed_overlap", model=FakeEmbeddingModel(),
    )
    assert replaced["doc_id"] != old_doc_id
    assert replaced["doc_id"] in db.documents
    assert old_doc_id not in db.documents
    assert db.documents[replaced["doc_id"]]["full_text"] == "New canonical content with Unicode 🧭."
    assert replaced["source_split"] == "managed_upload"
    assert replaced["source_sentences"] == []


def test_transaction_rolls_back_document_and_provenance_if_chunk_insert_fails(monkeypatch):
    db = MemoryDatabase()
    db.fail_chunk_insert = True
    _save_service_db(monkeypatch, db)
    with pytest.raises(RuntimeError, match="simulated"):
        create_upload(
            filename="one.txt", content=b"Atomic insert fixture.", title=None,
            chunking_strategy="paragraph", model=FakeEmbeddingModel(),
        )
    assert not db.documents
    assert not db.sources
    assert not db.chunks
    assert not db.uploads


def test_schema_proposal_is_additive_and_limits_owned_uploads():
    from pathlib import Path

    proposal = (Path(__file__).resolve().parents[1]
                / "migrations" / "proposals" / "phase6b_managed_uploads.sql")
    sql = proposal.read_text(encoding="utf-8").lower()
    assert "create table public.managed_uploads" in sql
    assert "references public.documents(doc_id) on delete restrict" in sql
    assert "references public.document_sources(source_id) on delete restrict" in sql
    assert "enable row level security" in sql
    assert "from public, anon, authenticated" in sql
    assert "drop table" not in sql and "delete from" not in sql and "truncate" not in sql

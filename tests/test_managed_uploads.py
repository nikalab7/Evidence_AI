from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.db.managed_uploads import (
    ConcurrentUploadUpdateError,
    UploadConflictError,
    UploadNotFoundError,
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
                "row_version": 1,
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
                       chunking_strategy=strategy, parser_metadata=self._payload(parser_metadata),
                       row_version=row["row_version"] + 1)
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
            row["row_version"],
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


def test_upload_replace_is_immediately_semantically_retrievable_with_exact_citation(monkeypatch):
    import app.retrieval.semantic as semantic
    import app.retrieval.keyword as keyword
    from app.reasoning.citations import validate_final_response
    from app.retrieval.engine import search

    db = MemoryDatabase()
    _save_service_db(monkeypatch, db)

    class SearchEmbeddingModel(FakeEmbeddingModel):
        def query_embed(self, _queries):
            return [[0.0] * 384]

    model = SearchEmbeddingModel()

    def materialize_chunk(chunk, *, with_validation):
        doc = db.documents[chunk["doc_id"]]
        full_text = doc["full_text"]
        sources = [source for source in db.sources.values()
                   if source["doc_id"] == chunk["doc_id"]]
        hit = {
            "chunk_id": chunk["chunk_id"], "doc_id": chunk["doc_id"],
            "chunk_position": chunk["chunk_position"], "chunk_text": full_text[
                chunk["start_char"]:chunk["end_char"]
            ], "metadata": doc["metadata"], "sources": sources,
            "cosine_distance": 0.2,
        }
        if with_validation:
            hit["validation_source"] = {
                "full_text": full_text, "start_char": chunk["start_char"],
                "end_char": chunk["end_char"],
            }
        return hit

    def fake_semantic(_conn, _vector, *, limit, include_validation_source=False,
                      exact_title_aliases=None, **_kwargs):
        # Model the observed miss from broad ANN search, then exact-title rescue.
        if exact_title_aliases is None:
            return []
        matches = []
        for chunk in db.chunks.values():
            titles = [source["title_normalized"] for source in db.sources.values()
                      if source["doc_id"] == chunk["doc_id"]]
            if set(titles).intersection(exact_title_aliases):
                matches.append(materialize_chunk(
                    chunk, with_validation=include_validation_source,
                ))
        return matches[:limit]

    def fake_keyword(_conn, query, *, limit, include_validation_source=False, **_kwargs):
        terms = {term.strip(".,?!;:").casefold() for term in query.split()}
        matches = []
        for chunk in db.chunks.values():
            hit = materialize_chunk(chunk, with_validation=include_validation_source)
            body_terms = set(hit["chunk_text"].casefold().split())
            if terms & body_terms:
                hit["keyword_score"] = 1.0
                matches.append(hit)
        return matches[:limit]

    monkeypatch.setattr(semantic, "semantic_search_chunks", fake_semantic)
    monkeypatch.setattr(keyword, "keyword_search_chunks", fake_keyword)
    title = "evidenceai_live_smoke_test"
    old_text = "The cobalt lighthouse stores 37 copper keys."
    new_text = "The cobalt lighthouse now stores 52 silver keys."
    created = create_upload(
        filename=f"{title}.txt", content=old_text.encode(), title=title,
        chunking_strategy="paragraph", model=model,
    )
    upload_id = UUID(created["upload_id"])
    old_doc_id = created["doc_id"]
    old_chunk_ids = {key for key, row in db.chunks.items() if row["doc_id"] == old_doc_id}
    initial = search(
        db, "how many copper keys does the cobalt lighthouse store?",
        mode="semantic", limit=3, candidate_limit=3, model=model,
        semantic_reference_query=f"According to {title}, how many copper keys?",
        include_evidence_text=True, include_validation_source=True,
    )
    assert initial and "37 copper keys" in initial[0]["evidence_text"]

    replacement = replace_upload(
        upload_id=upload_id, filename=f"{title}_updated.txt", content=new_text.encode(),
        title=title, chunking_strategy="paragraph", model=model,
    )
    assert replacement["title"] == title
    assert replacement["doc_id"] != old_doc_id
    assert old_doc_id not in db.documents
    assert old_chunk_ids.isdisjoint(db.chunks)

    question = (
        "According to evidenceai_live_smoke_test, how many silver keys "
        "does the cobalt lighthouse now store?"
    )
    semantic_results = search(
        db, "how many silver keys does the cobalt lighthouse now store?",
        mode="semantic", limit=3, candidate_limit=3, model=model,
        semantic_reference_query=question, include_evidence_text=True,
        include_validation_source=True,
    )
    keyword_results = search(
        db, question, mode="keyword", limit=3, candidate_limit=3,
        include_evidence_text=True, include_validation_source=True,
    )
    assert semantic_results and semantic_results[0]["doc_id"] == replacement["doc_id"]
    assert keyword_results and keyword_results[0]["doc_id"] == replacement["doc_id"]
    assert "52 silver keys" in semantic_results[0]["evidence_text"]
    assert "37 copper keys" not in semantic_results[0]["evidence_text"]

    evidence = {
        hit["chunk_id"]: {
            "doc_id": hit["doc_id"], "title": hit["title"],
            "titles": hit["titles"], "sources": hit["sources"],
            "evidence_text": hit["evidence_text"],
            "validation_source": hit["validation_source"],
        }
        for hit in semantic_results
    }
    verified = validate_final_response({
        "central_claim_id": "c1",
        "claims": [{"claim_id": "c1", "text": "It stores 52 silver keys.",
                    "citations": [{"chunk_id": semantic_results[0]["chunk_id"],
                                   "quote": "now stores 52 silver keys"}]}],
        "conflict_groups": [],
    }, evidence)
    assert verified["status"] == "answered"
    assert verified["claims"][0]["citations"][0]["quote"] == "now stores 52 silver keys"


def test_stale_same_content_replacement_is_rejected_by_monotonic_version(monkeypatch):
    import app.ingestion.managed_documents as service

    db = MemoryDatabase()
    _save_service_db(monkeypatch, db)
    created = create_upload(
        filename="one.txt", content=b"Stable content for a stale update.", title="Original",
        chunking_strategy="paragraph", model=FakeEmbeddingModel(),
    )
    upload_id = UUID(created["upload_id"])
    stale_version = created["row_version"]
    current_text = created["text"]
    parsed = service.parse_upload("renamed.txt", current_text.encode())
    replacement = service._prepare_upload_metadata_only(
        upload_id=upload_id, title="Renamed", text=current_text,
        chunking_strategy="paragraph",
    )
    upload_row = service._upload_row(
        upload_id=upload_id, document=replacement, parsed=parsed,
        original_filename="renamed.txt", title="Renamed", strategy="paragraph",
    )
    first = replace_managed_upload(
        db, upload_id=upload_id,
        expected_doc_id=created["doc_id"], expected_source_id=created["source_id"],
        expected_row_version=stale_version, document=replacement, upload=upload_row,
    )
    assert first["row_version"] == stale_version + 1

    with pytest.raises(ConcurrentUploadUpdateError, match="changed"):
        replace_managed_upload(
            db, upload_id=upload_id,
            expected_doc_id=created["doc_id"], expected_source_id=created["source_id"],
            expected_row_version=stale_version, document=replacement, upload=upload_row,
        )
    assert db.uploads[upload_id]["row_version"] == stale_version + 1


def test_stale_replacement_after_delete_cannot_recreate_upload(monkeypatch):
    db = MemoryDatabase()
    _save_service_db(monkeypatch, db)
    created = create_upload(
        filename="one.txt", content=b"Delete wins over stale replacement.", title=None,
        chunking_strategy="paragraph", model=FakeEmbeddingModel(),
    )
    assert remove_upload(UUID(created["upload_id"])) is True
    with pytest.raises(UploadNotFoundError, match="does not exist"):
        replace_managed_upload(
            db, upload_id=UUID(created["upload_id"]),
            expected_doc_id=created["doc_id"], expected_source_id=created["source_id"],
            expected_row_version=created["row_version"],
            document={}, upload={},
        )


def test_upload_chunk_limits_bound_long_paragraphs_and_total_chunks():
    import app.ingestion.managed_documents as service
    from app.ingestion.managed_documents import UploadInputError

    upload_id = UUID("3c949bb7-6b0b-480f-a403-9ef5f5ae16cc")
    long_text = "a" * 200_000
    paragraph_doc = service._prepare_upload_metadata_only(
        upload_id=upload_id, title="Long paragraph", text=long_text,
        chunking_strategy="paragraph",
    )
    assert len(paragraph_doc["chunks"]) == 200
    assert max(len(chunk["chunk_text"]) for chunk in paragraph_doc["chunks"]) <= 1_000
    assert all(
        paragraph_doc["full_text"][chunk["start_char"]:chunk["end_char"]] == chunk["chunk_text"]
        for chunk in paragraph_doc["chunks"]
    )

    fixed_doc = service._prepare_upload_metadata_only(
        upload_id=upload_id, title="Long fixed text", text=long_text,
        chunking_strategy="fixed_overlap",
    )
    assert len(fixed_doc["chunks"]) == 236
    assert len(fixed_doc["chunks"]) <= service.MAX_MANAGED_UPLOAD_CHUNKS

    too_many_paragraphs = "\n\n".join("x" for _ in range(service.MAX_MANAGED_UPLOAD_CHUNKS + 1))
    with pytest.raises(UploadInputError, match="more than 250 chunks"):
        service._prepare_upload_metadata_only(
            upload_id=upload_id, title="Many paragraphs", text=too_many_paragraphs,
            chunking_strategy="paragraph",
        )


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
    assert "create table if not exists public.managed_uploads" in sql
    assert "references public.documents(doc_id) on delete restrict" in sql
    assert "foreign key (source_id, doc_id)" in sql
    assert "references public.document_sources(source_id, doc_id) on delete restrict" in sql
    assert "managed_uploads_source_doc_fk" in sql
    assert "row_version bigint not null default 1" in sql
    assert "create unique index if not exists document_sources_source_doc_idx" in sql
    assert "enable row level security" in sql
    assert "from public, anon, authenticated" in sql
    assert "drop table" not in sql and "delete from" not in sql and "truncate" not in sql

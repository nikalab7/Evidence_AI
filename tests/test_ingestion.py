import hashlib

import pytest

from app.db.queries import (
    CHUNKS_SELECT_SQL,
    CHUNKS_UPSERT_SQL,
    DOCUMENTS_SELECT_SQL,
    DOCUMENTS_UPSERT_SQL,
    SOURCES_SELECT_SQL,
    SOURCES_UPSERT_SQL,
    insert_batch,
)
from app.ingestion.chunkers import paragraph_chunks
from app.ingestion.corpus_core import content_hash
from app.ingestion.deduplication import stable_chunk_id, stable_document_id, stable_source_id
from app.ingestion.indexer import embed_documents, prepare_document
from scripts.ingest_hotpotqa import (
    benchmark_cosine_search,
    validate_database_document_scope,
    validate_document_limit,
)


def _record(text="First paragraph.", aliases=None):
    aliases = aliases or [{"title": "Example", "sentences": ["First paragraph."]}]
    digest = content_hash(text)
    return {
        "doc_id": digest,
        "content_hash": digest,
        "text": text,
        "title": aliases[0]["title"],
        "source": "https://example.test/source",
        "source_revision": "revision-1",
        "source_split": "train",
        "source_variants": aliases,
    }


def test_paragraph_chunker_preserves_paragraph_text_and_positions():
    text = " First paragraph. \n\nSecond paragraph. "
    chunks = paragraph_chunks(text)
    assert chunks == [" First paragraph. ", "Second paragraph. "]
    doc = prepare_document(_record(text, [
        {"title": "Example", "sentences": ["First paragraph.", "Second paragraph."]},
    ]))
    assert [chunk["chunk_position"] for chunk in doc["chunks"]] == [0, 1]
    assert [chunk["chunk_text"] for chunk in doc["chunks"]] == chunks


def test_document_source_and_chunk_ids_are_stable():
    text = "Stable content."
    doc_id = stable_document_id(text)
    assert doc_id == hashlib.sha256(b"stable content.").hexdigest()
    assert stable_chunk_id(doc_id, "paragraph", 0, text) == stable_chunk_id(
        doc_id, "paragraph", 0, text,
    )
    assert stable_chunk_id(doc_id, "paragraph", 0, text) != stable_chunk_id(
        doc_id, "paragraph", 1, text,
    )
    source_id = stable_source_id(doc_id, "Alias", "source", "r1", "train", [text])
    assert source_id == stable_source_id(doc_id, "Alias", "source", "r1", "train", [text])
    assert source_id != stable_source_id(doc_id, "Other alias", "source", "r1", "train", [text])


def test_chunk_offsets_reconstruct_unicode_and_repeated_paragraphs_exactly():
    text = "雪🌱 e\u0301\n\nEcho.\n\nEcho."
    document = prepare_document(_record(text, [
        {"title": "Unicode", "sentences": ["Echo."]},
    ]))
    chunks = document["chunks"]
    assert [text[chunk["start_char"]:chunk["end_char"]] for chunk in chunks] == [
        chunk["chunk_text"] for chunk in chunks
    ]
    assert chunks[1]["chunk_text"] == chunks[2]["chunk_text"] == "Echo."
    assert chunks[1]["start_char"] < chunks[2]["start_char"]


def test_preparation_preserves_text_metadata_and_every_title_alias():
    aliases = [
        {"title": "Main title", "sentences": ["First sentence."]},
        {"title": "Alternate title", "sentences": ["First sentence."]},
    ]
    raw = _record("First sentence.", aliases)
    raw["application_note"] = {"owner": "team-a"}
    prepared = prepare_document(raw)
    assert prepared["full_text"] == raw["text"]
    assert prepared["metadata"] == {"application_note": {"owner": "team-a"}}
    assert [source["title_alias"] for source in prepared["sources"]] == [
        "Main title", "Alternate title",
    ]
    assert prepared["sources"][1]["sentences"] == ["First sentence."]
    assert "chunk_text" not in CHUNKS_UPSERT_SQL.split("FROM jsonb_to_recordset", 1)[0]
    assert "extensions.halfvec(384)" in CHUNKS_UPSERT_SQL


def test_embedding_batch_validates_dimensions_and_keeps_model_name():
    doc = prepare_document(_record())

    class FakeModel:
        def passage_embed(self, texts):
            return [[0.25] * 384 for _ in texts]

    embed_documents([doc], FakeModel(), "BAAI/bge-small-en-v1.5", batch_size=1)
    assert len(doc["chunks"][0]["embedding"]) == 384
    assert doc["chunks"][0]["embedding_model"] == "BAAI/bge-small-en-v1.5"


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _MemoryConnection:
    """Small conflict-aware fake for checking repeated batch insertion behavior."""

    def __init__(self):
        self.documents = {}
        self.sources = {}
        self.chunks = {}

    def execute(self, statement, params):
        if statement in (DOCUMENTS_UPSERT_SQL, SOURCES_UPSERT_SQL, CHUNKS_UPSERT_SQL):
            if statement == DOCUMENTS_UPSERT_SQL:
                table, key = self.documents, "doc_id"
            elif statement == SOURCES_UPSERT_SQL:
                table, key = self.sources, "source_id"
            else:
                table, key = self.chunks, "chunk_id"
            inserted = []
            for row in params[0].obj:
                if row[key] not in table:
                    table[row[key]] = row
                    inserted.append((row[key],))
            return _Result(inserted)

        if statement == DOCUMENTS_SELECT_SQL:
            fields = ("doc_id", "content_hash", "full_text", "metadata")
            table = self.documents
            key = "doc_id"
        elif statement == SOURCES_SELECT_SQL:
            fields = ("source_id", "doc_id", "title_alias", "title_normalized", "source_url",
                      "source_revision", "source_split", "sentences")
            table = self.sources
            key = "source_id"
        elif statement == CHUNKS_SELECT_SQL:
            fields = ("chunk_id", "doc_id", "chunk_position", "chunking_strategy",
                      "start_char", "end_char", "chunk_text", "embedding_model")
            table = self.chunks
            key = "chunk_id"
        else:
            raise AssertionError("unexpected SQL in ingestion batch test")
        return _Result([
            tuple(table[row_id][field] for field in fields)
            for row_id in params[0] if row_id in table
        ])


def test_repeated_batch_insert_is_idempotent_and_insert_only():
    doc = prepare_document(_record())

    class FakeModel:
        def passage_embed(self, texts):
            return [[0.1] * 384 for _ in texts]

    embed_documents([doc], FakeModel(), "BAAI/bge-small-en-v1.5")
    connection = _MemoryConnection()
    first = insert_batch(connection, [doc])
    second = insert_batch(connection, [doc])
    assert first == {"documents_inserted": 1, "sources_inserted": 1, "chunks_inserted": 1}
    assert second == {"documents_inserted": 0, "sources_inserted": 0, "chunks_inserted": 0}
    for statement in (DOCUMENTS_UPSERT_SQL, SOURCES_UPSERT_SQL, CHUNKS_UPSERT_SQL):
        assert "ON CONFLICT" in statement and "DO NOTHING" in statement
        assert "DO UPDATE" not in statement and "DELETE" not in statement


def test_model_loader_supports_local_four_thread_embedding_without_changing_default(monkeypatch, tmp_path):
    from app import model_cache

    calls = []
    monkeypatch.setattr(model_cache, "MODEL_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(
        model_cache, "TextEmbedding", lambda **kwargs: calls.append(kwargs) or object(),
    )
    model_cache.load_model("local", threads=4)
    assert calls[0]["threads"] == 4
    assert calls[0]["local_files_only"] is True
    with pytest.raises(ValueError, match="at least 1"):
        model_cache.load_model("local", threads=0)


def test_document_limit_enforces_milestone_ceiling():
    assert validate_document_limit(1) == 1
    assert validate_document_limit(1_000) == 1_000
    with pytest.raises(ValueError, match="between 1 and 1000"):
        validate_document_limit(0)
    with pytest.raises(ValueError, match="between 1 and 1000"):
        validate_document_limit(1_001)


def test_database_document_scope_refuses_out_of_prefix_rows_and_overflow():
    assert validate_database_document_scope({"a", "b"}, {"a", "b", "c"}) == 3
    with pytest.raises(ValueError, match="outside the selected corpus prefix"):
        validate_database_document_scope({"other"}, {"a", "b"})
    with pytest.raises(ValueError, match="exceeds the 1,000-document"):
        validate_database_document_scope(set(), {str(index) for index in range(1_001)})


def test_cosine_benchmark_identifies_independent_query_and_no_quality_claim(monkeypatch):
    import scripts.ingest_hotpotqa as ingestion

    def fake_search(_conn, _vector, limit):
        assert limit == 5
        return [{"chunk_id": "c1", "doc_id": "d1", "chunk_position": 0,
                 "cosine_distance": 0.2}]

    monkeypatch.setattr(ingestion, "cosine_search", fake_search)
    result = benchmark_cosine_search(object(), [0.0] * 384, warmups=0, runs=3)
    assert result["query_source"].startswith("independent natural-language query")
    assert result["retrieval_quality_evaluated"] is False
    assert result["measured_runs"] == 3
    assert result["latency_ms"]["minimum"] <= result["latency_ms"]["maximum"]

import pytest

from app.ingestion.chunkers import (
    FIXED_OVERLAP_STRATEGY,
    PARAGRAPH_STRATEGY,
    chunk_spans,
    fixed_overlap_chunk_spans,
    paragraph_chunk_spans,
)
from app.ingestion.indexer import prepare_document
from scripts.compare_chunking import compare


def test_paragraph_spans_reconstruct_exact_unicode_text_without_mutation():
    text = "ქართული სათაური\nfirst paragraph\n\n  দ্বিতური აბზაცი  \n\n終わり"
    spans = paragraph_chunk_spans(text)
    chunks = [text[start:end] for start, end in spans]
    assert chunks == ["ქართული სათაური\nfirst paragraph", "  দ্বিতური აბზაცი  ", "終わり"]
    assert all(text[start:end] == chunk for (start, end), chunk in zip(spans, chunks))


def test_bounded_paragraph_offsets_split_only_oversized_paragraphs():
    text = "\U0001f9ed" * 2_001 + "\n\nShort paragraph."
    spans = paragraph_chunk_spans(text, max_chunk_chars=1_000)
    pieces = [text[start:end] for start, end in spans]
    assert [len(piece) for piece in pieces] == [1_000, 1_000, 1, len("Short paragraph.")]
    assert "".join(pieces) == text.replace("\n\n", "")
    assert paragraph_chunk_spans("\U0001f9ed" * 2_001) == [(0, 2_001)]


def test_fixed_overlap_offsets_cover_exact_unicode_substrings():
    text = "αβγ🙂" * 20
    spans = fixed_overlap_chunk_spans(text, chunk_size=17, overlap=5)
    assert spans[0] == (0, 17)
    assert spans[1][0] == spans[0][1] - 5
    assert spans[-1][1] == len(text)
    assert all(0 <= start < end <= len(text) for start, end in spans)
    assert all(text[start:end] for start, end in spans)


@pytest.mark.parametrize(("chunk_size", "overlap"), [(0, 0), (10, -1), (10, 10)])
def test_fixed_overlap_rejects_invalid_parameters(chunk_size, overlap):
    with pytest.raises(ValueError):
        fixed_overlap_chunk_spans("some content", chunk_size=chunk_size, overlap=overlap)


def test_indexer_records_offsets_for_both_strategies():
    text = "First paragraph with emoji 🧭.\n\nSecond paragraph with ქართული."
    record = {
        "doc_id": "a" * 64,
        "content_hash": "a" * 64,
        "text": text,
        "source": "upload://fixture",
        "source_revision": "test",
        "source_split": "managed_upload",
        "source_variants": [{"title": "Fixture", "sentences": []}],
    }
    from app.ingestion.deduplication import stable_document_id
    record["doc_id"] = record["content_hash"] = stable_document_id(text)

    for strategy in (PARAGRAPH_STRATEGY, FIXED_OVERLAP_STRATEGY):
        prepared = prepare_document(record, chunking_strategy=strategy, allow_empty_source_sentences=True)
        for chunk in prepared["chunks"]:
            start, end = chunk["start_char"], chunk["end_char"]
            assert chunk["chunk_text"] == text[start:end]


def test_reproducible_fixture_compares_count_and_support_presence_not_ranking():
    result = compare()
    strategies = result["strategies"]
    assert strategies[PARAGRAPH_STRATEGY]["chunk_count"] == 4
    assert strategies[FIXED_OVERLAP_STRATEGY]["chunk_count"] < strategies[PARAGRAPH_STRATEGY]["chunk_count"]
    assert strategies[PARAGRAPH_STRATEGY]["support_sentence_coverage_percent"] == 100.0
    assert strategies[FIXED_OVERLAP_STRATEGY]["support_sentence_coverage_percent"] == 100.0
    assert result["retrieval_ranking_measured"] is False


def test_comparison_ranks_using_same_local_embedding_interface():
    from scripts.compare_chunking import _SUPPORTING_SENTENCES

    class FixtureEmbeddingModel:
        def query_embed(self, _queries):
            return [[1.0 if index == selected else 0.0 for index in range(384)]
                    for selected in range(3)]

        def passage_embed(self, chunks):
            return [[float(sentence in chunk) for sentence in _SUPPORTING_SENTENCES] + [0.0] * 381
                    for chunk in chunks]

    result = compare(FixtureEmbeddingModel())
    assert result["retrieval_ranking_measured"] is True
    for strategy in (PARAGRAPH_STRATEGY, FIXED_OVERLAP_STRATEGY):
        metrics = result["strategies"][strategy]["semantic_fixture"]
        assert metrics["recall_at_1"] == 1.0
        assert metrics["mrr"] == 1.0

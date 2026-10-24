import pytest

from app.db.queries import keyword_search_chunks
from app.evaluation.metrics import (
    aggregate_retrieval_metrics,
    indexed_evidence_pairs,
    select_eligible_questions,
    score_question,
)
from app.retrieval.engine import search
from app.retrieval.ranker import weighted_rrf
from app.retrieval.semantic import retrieve_semantic


def _hit(chunk_id, doc_id=None, score=0.0, titles=()):
    doc_id = doc_id or f"doc-{chunk_id}"
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "chunk_position": 0,
        "chunk_text": f"Text for {chunk_id}",
        "sources": [
            {"source_id": title, "title_alias": title, "source_url": f"https://example.test/{title}"}
            for title in titles
        ],
        "score": score,
    }


def test_weighted_rrf_uses_ranks_and_configurable_weights():
    semantic = [_hit("a", score=0.9), _hit("b", score=0.8)]
    keyword = [_hit("b", score=0.7), _hit("c", score=0.6)]
    ranked = weighted_rrf(
        semantic, keyword, semantic_weight=2.0, keyword_weight=1.0, rrf_k=60,
    )
    assert [hit["chunk_id"] for hit in ranked] == ["b", "a", "c"]
    assert ranked[0]["score"] == pytest.approx(2 / 62 + 1 / 61)
    assert ranked[0]["channel_ranks"] == {"semantic": 2, "keyword": 1}
    assert ranked[0]["channel_scores"] == {"semantic": 0.8, "keyword": 0.7}


def test_rrf_deduplicates_within_and_across_channels_and_merges_provenance():
    first = _hit("same", "doc-1", 0.9, titles=("Alpha",))
    duplicate = _hit("same", "doc-1", 0.5, titles=("Ignored duplicate",))
    other_channel = _hit("same", "doc-1", 0.8, titles=("Alternate title",))
    ranked = weighted_rrf([first, duplicate], [other_channel])
    assert len(ranked) == 1
    assert ranked[0]["score"] == pytest.approx(2 / 61)
    assert ranked[0]["channel_ranks"] == {"semantic": 1, "keyword": 1}
    assert {source["title_alias"] for source in ranked[0]["sources"]} == {
        "Alpha", "Alternate title",
    }


def test_rrf_is_deterministic_for_ties_and_handles_empty_or_single_channel_lists():
    ranked = weighted_rrf(
        [_hit("b", "doc-b"), _hit("a", "doc-a")],
        [_hit("a", "doc-a"), _hit("b", "doc-b")],
    )
    assert [hit["doc_id"] for hit in ranked] == ["doc-a", "doc-b"]
    assert weighted_rrf([], []) == []
    single_channel = weighted_rrf(
        [_hit("b", "doc-b"), _hit("a", "doc-a")], [],
        semantic_weight=1.0, keyword_weight=0.0,
    )
    assert len(single_channel) == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"semantic_weight": -1.0},
        {"keyword_weight": float("nan")},
        {"semantic_weight": 0.0, "keyword_weight": 0.0},
        {"rrf_k": 0},
    ],
)
def test_rrf_rejects_invalid_weights_and_constants(kwargs):
    with pytest.raises(ValueError):
        weighted_rrf([], [], **kwargs)


def test_rrf_requires_stable_ids_and_rejects_conflicting_chunk_ownership():
    with pytest.raises(ValueError, match="chunk_id"):
        weighted_rrf([{"doc_id": "doc"}], [])
    with pytest.raises(ValueError, match="multiple documents"):
        weighted_rrf([_hit("same", "doc-a")], [_hit("same", "doc-b")])


def test_semantic_retrieval_validates_query_embedding_dimensions_before_database_call():
    class BadModel:
        def query_embed(self, _queries):
            return [[0.1] * 3]

    with pytest.raises(ValueError, match="384"):
        retrieve_semantic(object(), BadModel(), "a question")


def test_keyword_sql_binds_user_query_and_filter_values():
    class Result:
        def fetchall(self):
            return []

    class Connection:
        def execute(self, statement, params):
            self.statement = statement
            self.params = params
            return Result()

    conn = Connection()
    query = "safe query'; DROP TABLE chunks; --"
    keyword_search_chunks(
        conn, query,
        filters={"source_split": "train", "chunking_strategy": "paragraph"},
    )
    assert conn.params == (query, "paragraph", "train", 10)
    assert "DROP TABLE" not in str(conn.statement)
    rendered = str(conn.statement)
    assert "WITH RECURSIVE" in rendered
    assert "tsvector_to_array(to_tsvector('english'" in rendered
    assert "plainto_tsquery('english'" in rendered
    assert "query_fold.tsquery || query_terms.term_query" in rendered
    assert "websearch_to_tsquery" not in rendered


@pytest.mark.parametrize("query", ["", "   ", "\t\n"])
def test_empty_keyword_query_returns_no_results_without_database_call(query):
    class Connection:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("empty query must not reach the database")

    assert keyword_search_chunks(Connection(), query) == []


def test_keyword_query_preserves_punctuation_and_duplicate_terms_as_bound_input():
    class Result:
        def fetchall(self):
            return []

    class Connection:
        def execute(self, statement, params):
            self.statement = statement
            self.params = params
            return Result()

    conn = Connection()
    query = "Runners, running RUNNER! \"OR\" -- 'quoted'"
    assert keyword_search_chunks(conn, query) == []
    assert conn.params == (query, 10)


def test_engine_returns_source_titles_excerpts_and_ranked_scores(monkeypatch):
    import app.retrieval.engine as engine

    monkeypatch.setattr(engine, "retrieve_keyword", lambda *_args, **_kwargs: [
        _hit("c1", "d1", 0.2, titles=("Example title",))
    ])
    results = search(object(), "question", mode="keyword", limit=1, candidate_limit=1)
    assert results[0]["chunk_id"] == "c1"
    assert results[0]["doc_id"] == "d1"
    assert results[0]["title"] == "Example title"
    assert results[0]["text_excerpt"] == "Text for c1"
    assert results[0]["score"] == 0.2
    assert results[0]["rank"] == 1


def test_engine_returns_empty_results_for_blank_keyword_query_without_database_call():
    assert search(object(), "  ", mode="keyword") == []


def test_evidence_gate_requires_all_normalized_title_sentence_pairs():
    questions = [
        {"question_id": "complete", "supporting_evidence": [
            {"title": "  Alpha ", "sentence": "First   fact."},
            {"title": "Beta", "sentence": "Second fact."},
        ]},
        {"question_id": "partial", "supporting_evidence": [
            {"title": "Alpha", "sentence": "First fact."},
            {"title": "Beta", "sentence": "Missing fact."},
        ]},
    ]
    evidence = indexed_evidence_pairs([
        {"title_normalized": "alpha", "sentences": ["First fact."]},
        {"title_normalized": "beta", "sentences": ["Second fact."]},
    ])
    eligible, excluded = select_eligible_questions(questions, evidence)
    assert [question["question_id"] for question in eligible] == ["complete"]
    assert [question["question_id"] for question in excluded] == ["partial"]


def test_indexed_evidence_gate_requires_support_sentence_in_chunk_text():
    evidence = indexed_evidence_pairs([{
        "title_normalized": "alpha",
        "sentences": ["A stored provenance fact.", "A missing chunk fact."],
        "chunk_text": "A stored provenance fact.",
    }])
    assert evidence == {("alpha", "a stored provenance fact.")}


def test_recall_and_mrr_use_supporting_title_aliases_and_aggregate_by_question():
    question = {
        "question_id": "q1",
        "supporting_evidence": [
            {"title": "Alpha", "sentence": "Fact one."},
            {"title": "Beta", "sentence": "Fact two."},
        ],
    }
    ranked = [
        _hit("x", "doc-x", titles=("Unrelated",)),
        _hit("a", "doc-a", titles=("Alpha",)),
        _hit("b", "doc-b", titles=("Beta",)),
    ]
    scored = score_question(question, ranked)
    assert scored == {"recall@5": 1.0, "recall@10": 1.0, "mrr": 0.5}
    aggregate = aggregate_retrieval_metrics([question], {"q1": ranked})
    assert aggregate["question_count"] == 1
    assert aggregate["mrr"] == pytest.approx(0.5)


def test_metrics_handle_no_matching_results_and_reject_empty_evaluation_sets():
    question = {
        "question_id": "q1",
        "supporting_evidence": [{"title": "Gold", "sentence": "Fact."}],
    }
    assert score_question(question, []) == {"recall@5": 0.0, "recall@10": 0.0, "mrr": 0.0}
    with pytest.raises(ValueError, match="without eligible"):
        aggregate_retrieval_metrics([], {})

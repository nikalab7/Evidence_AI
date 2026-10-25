import math

import pytest

from app.db.queries import keyword_search_chunks
from app.retrieval.keywords import DEFAULT_COMMON_TERM_THRESHOLD, protected_query_text
from app.retrieval.ranker import weighted_rrf
from scripts.evaluate_retrieval_tuning import (
    HYBRID_GRID,
    HybridConfig,
    rank_cached_candidates,
    select_best_positive_hybrid,
)


def test_protected_terms_keep_names_acronyms_numbers_and_deduplicate():
    assert protected_query_text(
        "What did ACME-42's U.S. branch do in 1969? ACME-42"
    ) == "What ACME-42 U.S. 1969"


def test_lowercase_terms_are_not_selected_or_dropped_by_the_python_heuristic():
    assert protected_query_text("where did the club move in 2024") == "2024"


def test_protected_term_tokenizer_handles_punctuation_and_unicode():
    assert protected_query_text("Élodie won 2-1; U.S.A.! ") == "Élodie 2-1 U.S.A."
    assert protected_query_text("?!... ") == ""


def test_protected_query_text_rejects_non_string_input():
    with pytest.raises(ValueError, match="query must be a string"):
        protected_query_text(None)


def test_informative_keyword_sql_uses_stats_and_binds_all_query_values():
    class Result:
        def fetchall(self):
            return []

    class Connection:
        def execute(self, statement, params):
            self.statement = str(statement)
            self.params = params
            return Result()

    conn = Connection()
    query = "What did Alpha use in 2001?"
    keyword_search_chunks(
        conn, query, strategy="informative", common_term_threshold=0.1,
    )

    assert conn.params == (query, "What Alpha 2001", 0.1, 10)
    assert "FROM pg_stats" in conn.statement
    assert "most_common_elem_freqs" in conn.statement
    assert "document_frequency < %s" in conn.statement
    assert "WHERE NOT EXISTS (SELECT 1 FROM retained_lexemes)" in conn.statement
    assert query not in conn.statement


def test_informative_keyword_binds_punctuation_and_special_characters():
    class Result:
        def fetchall(self):
            return []

    class Connection:
        def execute(self, statement, params):
            self.statement = str(statement)
            self.params = params
            return Result()

    conn = Connection()
    query = "Runners, running RUNNER! 'OR' -- DROP TABLE chunks; --"
    assert keyword_search_chunks(conn, query, strategy="informative") == []

    assert conn.params[0] == query
    assert "DROP TABLE" not in conn.statement
    assert query not in conn.statement


def test_informative_stopword_only_query_has_no_terms_to_match_or_fallback():
    class Result:
        def fetchall(self):
            return []

    class Connection:
        def execute(self, statement, params):
            self.statement = str(statement)
            self.params = params
            return Result()

    conn = Connection()
    assert keyword_search_chunks(conn, "the and of", strategy="informative") == []

    assert conn.params == ("the and of", "", DEFAULT_COMMON_TERM_THRESHOLD, 10)
    assert "WHERE NOT EXISTS (SELECT 1 FROM retained_lexemes)" in conn.statement


@pytest.mark.parametrize("threshold", [-0.01, 1.01, math.nan, math.inf, None, "not-a-number"])
def test_informative_keyword_rejects_invalid_frequency_threshold(threshold):
    with pytest.raises(ValueError, match="threshold must be between 0 and 1"):
        keyword_search_chunks(object(), "query", strategy="informative", common_term_threshold=threshold)


def test_keyword_retrieval_rejects_unknown_strategy():
    with pytest.raises(ValueError, match="strategy must be"):
        keyword_search_chunks(object(), "query", strategy="random")


def test_informative_results_participate_in_weighted_hybrid_ranking():
    def hit(chunk_id, doc_id, score):
        return {
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "score": score,
            "sources": [],
        }

    semantic = [hit("semantic-a", "doc-a", 0.9), hit("shared", "doc-b", 0.8)]
    informative = [hit("shared", "doc-b", 3.0), hit("informative-c", "doc-c", 2.0)]

    fused = weighted_rrf(
        semantic, informative, semantic_weight=1.0, keyword_weight=0.5, rrf_k=20,
    )
    assert [item["chunk_id"] for item in fused] == ["shared", "semantic-a", "informative-c"]
    assert fused[0]["channel_ranks"] == {"semantic": 2, "keyword": 1}


def test_tuning_grid_has_all_eight_requested_configurations():
    assert len(HYBRID_GRID) == 8
    assert {config.semantic_weight for config in HYBRID_GRID} == {1.0}
    assert {config.keyword_weight for config in HYBRID_GRID} == {0.0, 0.25, 0.5, 1.0}
    assert {config.rrf_k for config in HYBRID_GRID} == {20, 60}
    assert DEFAULT_COMMON_TERM_THRESHOLD == 0.05


def test_best_hybrid_selection_excludes_semantic_only_zero_keyword_weight():
    summary = {}
    for config in HYBRID_GRID:
        key = f"kw={config.keyword_weight:g},k={config.rrf_k}"
        score = 1.0 if config.keyword_weight == 0 else 0.7
        recall5 = 0.5
        if config.keyword_weight == 0.25 and config.rrf_k == 20:
            score, recall5 = 0.8, 0.9
        summary[key] = {
            "metrics": {"recall@10": score, "recall@5": recall5, "mrr": score},
            "latency": {"p95_nearest_rank_ms": 10.0},
        }

    selected = select_best_positive_hybrid(summary)
    assert selected == HybridConfig(semantic_weight=1.0, keyword_weight=0.25, rrf_k=20)


def test_cached_grid_fusion_is_deterministic_for_same_candidates():
    semantic = [{"chunk_id": "s", "doc_id": "doc-s", "score": 0.8}]
    keyword = [{"chunk_id": "k", "doc_id": "doc-k", "score": 2.0}]
    config = HybridConfig(semantic_weight=1.0, keyword_weight=0.25, rrf_k=20)

    first = rank_cached_candidates(semantic, keyword, config)
    second = rank_cached_candidates(semantic, keyword, config)

    assert [hit["chunk_id"] for hit in first] == [hit["chunk_id"] for hit in second]
    assert first[0]["chunk_id"] == "s"


def test_engine_exposes_informative_strategy_without_changing_legacy_default(monkeypatch):
    import app.retrieval.engine as engine

    calls = []

    def fake_keyword(*_args, **kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(engine, "retrieve_keyword", fake_keyword)
    engine.search(object(), "query", mode="keyword")
    engine.search(object(), "query", mode="keyword", keyword_strategy="informative")

    assert calls[0]["strategy"] == "or"
    assert calls[1]["strategy"] == "informative"
    assert calls[1]["common_term_threshold"] == DEFAULT_COMMON_TERM_THRESHOLD

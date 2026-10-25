import json

import pytest

from app.ingestion.corpus_core import content_hash
from scripts.ingest_phase5 import (
    CapacityGateError,
    estimate_final_database_size,
    load_unique_prefix,
    validate_stage_target,
    validate_stage_transition,
)


def _corpus_record(text: str) -> dict:
    digest = content_hash(text)
    return {
        "doc_id": digest,
        "content_hash": digest,
        "text": text,
        "source": "https://example.test/hotpot",
        "source_revision": "test-revision",
        "source_split": "train",
        "source_variants": [{"title": f"Title {text}", "sentences": [text]}],
        "difficulty": "medium",
    }


def test_phase5_targets_are_fixed_and_bounded():
    assert validate_stage_target(10_000) == 10_000
    assert validate_stage_target(50_000) == 50_000
    for invalid in (0, 1_000, 10_001, 50_001):
        with pytest.raises(ValueError):
            validate_stage_target(invalid)


def test_stage_transition_requires_verified_baseline_and_prior_checkpoint():
    with pytest.raises(ValueError, match="database has 999"):
        validate_stage_transition(10_000, 999)
    assert validate_stage_transition(10_000, 1_000) is None
    with pytest.raises(ValueError, match="requires the prior 10000-document checkpoint"):
        validate_stage_transition(25_000, 9_999)
    assert validate_stage_transition(25_000, 10_000) is None
    with pytest.raises(ValueError, match="beyond target"):
        validate_stage_transition(10_000, 10_001)


def test_corpus_prefix_uses_stable_unique_document_ids(tmp_path):
    path = tmp_path / "corpus.jsonl"
    records = [_corpus_record("first"), _corpus_record("first"), _corpus_record("second")]
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

    documents, records_read = load_unique_prefix(path, 2)

    assert [document["full_text"] for document in documents] == ["first", "second"]
    assert len({document["doc_id"] for document in documents}) == 2
    assert records_read == 3
    assert documents[0]["metadata"] == {"difficulty": "medium"}


def test_capacity_projection_scales_target_relations_then_adds_margin():
    metrics = {
        "database_size_bytes": 1_000_000,
        "tables": {
            "documents": {"total_relation_size_bytes": 40_000},
            "document_sources": {"total_relation_size_bytes": 20_000},
            "chunks": {"total_relation_size_bytes": 40_000},
        },
    }
    result = estimate_final_database_size(metrics, 1_000)

    assert result["non_target_database_bytes"] == 900_000
    assert result["linear_50k_database_bytes"] == 5_900_000
    assert result["projected_50k_database_bytes_with_margin"] == 7_375_000


def test_capacity_projection_refuses_invalid_counts_and_oversized_relations():
    metrics = {
        "database_size_bytes": 10,
        "tables": {"documents": {"total_relation_size_bytes": 11}},
    }
    with pytest.raises(ValueError, match="without indexed documents"):
        estimate_final_database_size(metrics, 0)
    with pytest.raises(ValueError, match="exceed total database size"):
        estimate_final_database_size(metrics, 1)


def test_capacity_projection_counts_empty_managed_table_as_fixed_storage():
    metrics = {
        "database_size_bytes": 1_000_000,
        "tables": {
            "documents": {"total_relation_size_bytes": 40_000},
            "document_sources": {"total_relation_size_bytes": 20_000},
            "chunks": {"total_relation_size_bytes": 40_000},
        },
        "additional_tables": {
            "managed_uploads": {"rows": 0, "total_relation_size_bytes": 10_000},
        },
    }
    projection = estimate_final_database_size(metrics, 1_000)
    assert projection["current_target_relation_bytes"] == 110_000
    assert projection["non_target_database_bytes"] == 890_000
    assert projection["linear_50k_database_bytes"] == 5_900_000
    assert projection["projected_50k_database_bytes_with_margin"] == 7_375_000


def test_capacity_gate_error_retains_verified_current_count():
    error = CapacityGateError("stop", current_documents=12_345)
    assert str(error) == "stop"
    assert error.current_documents == 12_345

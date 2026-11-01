"""Offline unit tests for paired Thinking A/B result comparison."""

import pytest

from scripts.compare_thinking_runs import compare


def _row(correct: bool, *, case_id: str = "case-1", status: str = "answered"):
    return {
        "case_id": case_id,
        "retrieval_mode": "semantic",
        "dataset_sha256": "dataset-123",
        "model": "gemini-3.5-flash-lite",
        "category": "multi_hop",
        "execution_mode": "live",
        "answer_correctness": correct,
        "predicted_status": status,
        "question": "example question",
        "predicted_answer": "example answer",
        "error_type": None,
        "latency_seconds": 4.0,
        "draft_citation_count": 2,
        "verified_citation_count": 2,
        "tool_call_count": 2,
        "api_request_count": 3,
    }


def test_paired_comparison_counts_correctness_changes():
    a = {("case-1", "semantic"): _row(False)}
    b = {("case-1", "semantic"): _row(True)}
    result = compare(a, b)
    assert result["matched_multi_hop_cases"] == 1
    assert result["correctness_delta"] == 1
    assert len(result["case_changes"]) == 1
    assert result["baseline"]["gemini_http_requests"] == 3


def test_paired_comparison_refuses_different_dataset():
    a = {("case-1", "semantic"): _row(False)}
    b_row = _row(True)
    b_row["dataset_sha256"] = "wrong-dataset"
    with pytest.raises(ValueError, match="mismatched dataset_sha256"):
        compare(a, {("case-1", "semantic"): b_row})


def test_paired_comparison_requires_shared_question():
    with pytest.raises(ValueError, match="no paired"):
        compare({("a", "semantic"): _row(False, case_id="a")},
                {("b", "semantic"): _row(True, case_id="b")})

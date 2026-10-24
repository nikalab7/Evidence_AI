import json
from pathlib import Path

import pytest

from app.reasoning.citations import reconstruct_chunk_text, validate_final_response


def _evidence(text, *, start=0, end=None, chunk_id="chunk-a"):
    end = len(text) if end is None else end
    return {chunk_id: {
        "doc_id": "doc-a", "title": "Verified title", "titles": ["Verified title"],
        "sources": [{"source_id": "source-a", "title_alias": "Verified title"}],
        "evidence_text": text[start:end],
        "validation_source": {"full_text": text, "start_char": start, "end_char": end},
    }}


def test_unicode_offset_reconstruction_and_whitespace_normalized_quote():
    text = "prefix café\tgives\n€20 payment. suffix"
    start, end = text.index("café"), text.index(". suffix") + 1
    assert reconstruct_chunk_text({"full_text": text, "start_char": start, "end_char": end}) == "café\tgives\n€20 payment."
    result = validate_final_response({
        "central_claim_id": "c1", "claims": [{"claim_id": "c1", "text": "The price is €20.",
            "citations": [{"chunk_id": "chunk-a", "quote": "café gives €20\npayment."}]}],
        "conflict_groups": [],
    }, _evidence(text, start=start, end=end))
    assert result["status"] == "answered"
    assert result["claims"][0]["citations"][0]["sources"][0]["source_id"] == "source-a"


def test_offsets_disambiguate_repeated_text_in_one_document():
    text = "Repeat fact. Middle. Repeat fact."
    start = text.rindex("Repeat fact.")
    assert reconstruct_chunk_text({"full_text": text, "start_char": start,
                                   "end_char": start + len("Repeat fact.")}) == "Repeat fact."


def test_fabricated_chunk_or_source_reference_drops_claim_and_abstains():
    result = validate_final_response({
        "central_claim_id": "main", "claims": [{"claim_id": "main", "text": "Unsupported.",
            "citations": [{"chunk_id": "invented", "quote": "made up"}]}],
        "conflict_groups": [],
    }, _evidence("Known fact."))
    assert result["status"] == "insufficient"
    assert result["claims"] == []

    result = validate_final_response({
        "central_claim_id": "main", "claims": [{"claim_id": "main", "text": "Known fact.",
            "citations": [{"chunk_id": "chunk-a", "quote": "Known fact.", "source_url": "fake"}]}],
        "conflict_groups": [],
    }, _evidence("Known fact."))
    assert result["status"] == "insufficient"


def test_missing_central_evidence_abstains_even_when_secondary_claim_is_valid():
    result = validate_final_response({
        "central_claim_id": "missing", "claims": [{"claim_id": "side", "text": "Known fact.",
            "citations": [{"chunk_id": "chunk-a", "quote": "Known fact."}]}],
        "conflict_groups": [],
    }, _evidence("Known fact."))
    assert result["status"] == "insufficient"
    assert result["answer"].startswith("Insufficient evidence")
    assert [claim["claim_id"] for claim in result["claims"]] == ["side"]


def test_invalid_quotes_are_dropped_while_verified_claims_remain():
    result = validate_final_response({
        "central_claim_id": "supported", "claims": [
            {"claim_id": "supported", "text": "Known fact.",
             "citations": [{"chunk_id": "chunk-a", "quote": "Known fact."}]},
            {"claim_id": "unsupported", "text": "Different fact.",
             "citations": [{"chunk_id": "chunk-a", "quote": "Different fact."}]},
        ], "conflict_groups": [],
    }, _evidence("Known fact."))
    assert result["status"] == "answered"
    assert [item["claim_id"] for item in result["claims"]] == ["supported"]
    assert result["dropped_claim_ids"] == ["unsupported"]


def test_multihop_claim_can_require_quotes_from_multiple_retrieved_chunks():
    evidence = {**_evidence("A links to B.", chunk_id="chunk-a"),
                **_evidence("B names answer C.", chunk_id="chunk-b")}
    result = validate_final_response({
        "central_claim_id": "bridge", "claims": [{"claim_id": "bridge", "text": "The evidence links A to C.",
            "citations": [{"chunk_id": "chunk-a", "quote": "A links to B."},
                          {"chunk_id": "chunk-b", "quote": "B names answer C."}]}],
        "conflict_groups": [],
    }, evidence)
    assert result["status"] == "answered"
    assert len(result["claims"][0]["citations"]) == 2


def test_conflict_fixture_uses_only_mock_evidence_and_verified_quotes():
    fixture = json.loads((Path(__file__).parent / "fixtures/phase3_conflict_case.json").read_text(encoding="utf-8"))
    retrieved = {}
    for item in fixture["retrieved"]:
        retrieved[item["chunk_id"]] = {
            **item, "evidence_text": item["full_text"][item["start_char"]:item["end_char"]],
            "validation_source": {key: item[key] for key in ("full_text", "start_char", "end_char")},
        }
    result = validate_final_response(fixture["draft"], retrieved)
    assert result["status"] == "conflicting"
    assert len(result["claims"]) == 2
    assert result["conflict_groups"] == [["claim-outage", "claim-healthy"]]

    fixture["draft"]["claims"][1]["citations"][0]["quote"] = "Not in retrieved text."
    rejected = validate_final_response(fixture["draft"], retrieved)
    assert rejected["status"] == "answered"
    assert rejected["dropped_claim_ids"] == ["claim-healthy"]
    assert rejected["conflict_groups"] == []


@pytest.mark.parametrize("source", [
    {"full_text": "abc", "start_char": -1, "end_char": 2},
    {"full_text": "abc", "start_char": 2, "end_char": 4},
    {"full_text": "abc", "start_char": 1, "end_char": 1},
])
def test_invalid_offsets_fail_closed(source):
    with pytest.raises(ValueError, match="offset"):
        reconstruct_chunk_text(source)

import copy
import json
from pathlib import Path

import pytest

from app.api.investigations import _public_result, _safe_diagnostic_log
from app.evaluation.final_runner import _fixture_search, read_jsonl, sha256_file
from app.evaluation.quality_baseline import baseline_agent, baseline_validator
from app.evaluation.quality_dev import load_cases
from app.llm.agent import investigate
from app.llm.schemas import FunctionCall, LLMResponse
from app.reasoning.citations import validate_final_response
from scripts.prepare_quality_dev import DEV, select_questions


def _fixtures():
    return [c for c in load_cases()[0] if c["execution_mode"] == "fixture"]


def _evidence(case):
    return {hit["chunk_id"]: hit for hit in _fixture_search(case)(None, "test", limit=32)}


@pytest.mark.parametrize("index", range(10))
def test_new_fixture_replays_preserve_expected_status_and_quotes(index):
    case = _fixtures()[index]
    result = validate_final_response(case["replay_draft"], _evidence(case))
    assert result["status"] == case["expected_status"]
    for claim in result["claims"]:
        for citation in claim["citations"]:
            assert citation["quote"] in _evidence(case)[citation["chunk_id"]]["evidence_text"]


def test_baseline_reproduces_empty_central_conflict_failure_without_llm():
    case = _fixtures()[0]
    draft, evidence = case["replay_draft"], _evidence(case)
    assert baseline_validator()(draft, evidence)["status"] == "insufficient"
    assert validate_final_response(draft, evidence)["status"] == "conflicting"


@pytest.mark.parametrize("central", ["missing", [], None])
def test_invalid_nonempty_central_claim_cannot_be_rescued_by_secondary_conflicts(central):
    case = _fixtures()[0]
    draft = copy.deepcopy(case["replay_draft"])
    draft["central_claim_id"] = central
    assert validate_final_response(draft, _evidence(case))["status"] == "insufficient"


@pytest.mark.parametrize("change", ["bad_quote", "unknown_chunk", "unknown_member", "same_member"])
def test_incomplete_conflict_evidence_never_creates_a_conflict(change):
    case = _fixtures()[0]
    draft = copy.deepcopy(case["replay_draft"])
    if change == "bad_quote":
        draft["claims"][1]["citations"][0]["quote"] = "A paraphrased private sentence."
    elif change == "unknown_chunk":
        draft["claims"][1]["citations"][0]["chunk_id"] = "not-retrieved"
    elif change == "unknown_member":
        draft["conflict_groups"] = [["c1", "not-a-claim"]]
    else:
        draft["conflict_groups"] = [["c1", "c1"]]
    assert validate_final_response(draft, _evidence(case))["status"] == "insufficient"


def test_atomic_claim_rejection_diagnoses_each_quote_without_repairing_it():
    case = _fixtures()[0]
    draft = copy.deepcopy(case["replay_draft"])
    draft["central_claim_id"] = "c1"
    draft["conflict_groups"] = []
    draft["claims"] = draft["claims"][:1]
    draft["claims"][0]["citations"].append({
        "chunk_id": case["fixture_evidence"][0]["chunk_id"],
        "quote": case["fixture_evidence"][1]["sentence"],
    })
    diagnostics = {}
    result = validate_final_response(draft, _evidence(case), diagnostics=diagnostics)
    assert result["status"] == "insufficient"
    assert result["claims"] == []
    assert [c["outcome"] for c in diagnostics["citation_checks"]] == ["verified", "quote_not_verbatim"]
    assert "quote" not in json.dumps(diagnostics).replace("quote_not_verbatim", "")


class ScriptedClient:
    settings = type("Settings", (), {"gemini_model": "gemini-3.5-flash-lite"})()

    def __init__(self, drafts):
        self.responses = iter(drafts)
        self.requests = []

    def generate(self, *_args, **_kwargs):
        self.requests.append(copy.deepcopy(_args[0]))
        text, functions = next(self.responses)
        return LLMResponse(text, functions, {"parts": []}, [
            {"latency_seconds": .001, "http_status": 200, "usage": {}},
        ])


def test_frozen_baseline_agent_replay_preserves_original_result_and_private_draft():
    case = _fixtures()[0]
    client = ScriptedClient([
        (None, [FunctionCall("search_evidence", {"query": "synthetic baseline query"})]),
        ("Ready", []), (json.dumps(case["replay_draft"]), []),
    ])
    result = baseline_agent()(case["question"], conn=object(), embedding_model=None,
                               llm_client=client, search_function=_fixture_search(case),
                               capture_evaluation_details=True)
    assert result.status == "insufficient"
    assert result.trace["evaluation_final_draft"] == case["replay_draft"]
    assert result.trace["evidence_diagnostic"]["outcome"] == "central_claim_unverified"
    assert result.trace["api_usage"]["request_count"] == 3


def test_retained_fix_preserves_baseline_generation_messages_and_request_count():
    case = _fixtures()[0]
    responses = [
        (None, [FunctionCall("search_evidence", {"query": "same synthetic query"})]),
        ("Ready", []), (json.dumps(case["replay_draft"]), []),
    ]
    before, retained = ScriptedClient(responses), ScriptedClient(responses)
    old = baseline_agent()(case["question"], conn=object(), embedding_model=None,
                            llm_client=before, search_function=_fixture_search(case))
    new = investigate(case["question"], conn=object(), embedding_model=None,
                       llm_client=retained, search_function=_fixture_search(case))
    assert before.requests == retained.requests
    assert len(retained.requests) == 3
    assert old.status == "insufficient"
    assert new.status == "conflicting"


@pytest.mark.parametrize("capture", [False, True])
def test_agent_records_private_drafts_only_when_requested_and_keeps_public_output_safe(capture):
    case = _fixtures()[0]
    client = ScriptedClient([
        (None, [FunctionCall("search_evidence", {"query": "private query marker"})]),
        ("Ready", []), (json.dumps(case["replay_draft"]), []),
    ])
    result = investigate(case["question"], conn=object(), embedding_model=None,
                         llm_client=client, search_function=_fixture_search(case),
                         capture_evaluation_details=capture)
    assert result.status == "conflicting"
    assert result.trace["evidence_diagnostic"]["outcome"] == "citations_verified"
    assert result.trace["api_usage"]["request_count"] == 3
    assert ("evaluation_final_draft" in result.trace) is capture
    public = _public_result(result)
    logged = _safe_diagnostic_log(result.trace, result.status, "semantic")
    assert public["status"] == "conflicting"
    assert "private query marker" not in json.dumps(public) + json.dumps(logged)
    assert "evaluation_final_draft" not in json.dumps(public) + json.dumps(logged)


def test_multihop_quotes_from_separate_tool_calls_are_aggregated():
    case = _fixtures()[-1]
    hits = list(_evidence(case).values())
    turns = iter([[hits[0]], [hits[1]]])
    client = ScriptedClient([
        (None, [FunctionCall("search_evidence", {"query": "founder partner"})]),
        (None, [FunctionCall("search_evidence", {"query": "partner child prize"})]),
        ("Ready", []), (json.dumps(case["replay_draft"]), []),
    ])
    result = investigate(case["question"], conn=object(), embedding_model=None,
                         llm_client=client, search_function=lambda *_args, **_kwargs: next(turns))
    assert result.status == "answered"
    assert len(result.claims[0]["citations"]) == 2
    assert result.trace["api_usage"]["request_count"] == 4
    assert result.trace["evidence_diagnostic"]["retrieved_chunk_count"] == 2


def test_twenty_questions_are_unchanged_stratified_members_of_development_set():
    cases, manifest = load_cases()
    original = read_jsonl(DEV)
    selected = select_questions(original)
    assert len(selected) == 20
    assert all(row in original for row in selected)
    assert [r["question_id"] for r in selected] == manifest["selected_ids"]
    assert sum(r["type"] == "bridge" for r in selected) == 10
    assert sum(r["type"] == "comparison" for r in selected) == 10
    assert len(cases) == 30


def test_original_final_dataset_and_report_still_match_frozen_diagnosis():
    root = Path(__file__).resolve().parents[1]
    frozen = json.loads((root / "reports/phase7_4_diagnosis.json").read_text(encoding="utf-8"))
    for path, digest in frozen["frozen_files"].items():
        if (root / path).exists():
            assert sha256_file(root / path) == digest

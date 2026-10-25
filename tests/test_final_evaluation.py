import json
from pathlib import Path

import pytest

from app.config import Settings
from app.evaluation.answer_metrics import answer_span_match, case_quality, evidence_coverage
from app.evaluation.final_runner import (
    _ranked_unique_hits,
    _failure_categories,
    _repair_incomplete_result_tail,
    _recent_reservations,
    audit_plan,
    build_run_key,
    make_case_result,
    require_complete_indexed_coverage,
    reserve_investigation,
    run_live,
)
from app.evaluation.reporting import render_final_report
from app.db.queries import read_indexed_source_evidence_for_references
from app.evaluation.metrics import indexed_evidence_pairs
from app.llm.agent import investigate
from app.llm.schemas import FunctionCall, LLMResponse
from scripts import prepare_final_eval as prepare
from scripts import evaluate_final


def _all_candidate_pairs(candidates):
    return {
        (prepare.normalize_text(fact["title"]), prepare.normalize_text(fact["sentence"]))
        for case in candidates for fact in case["supporting_evidence"]
    }


def test_final_dataset_is_fixed_mixed_and_preserves_candidate_answers(monkeypatch):
    candidates = prepare.read_jsonl(prepare.CANDIDATES)
    pairs = _all_candidate_pairs(candidates)
    monkeypatch.setattr(prepare, "corpus_pairs", lambda _path: (pairs, "local-corpus-hash"))
    first, _ = prepare.build_dataset(candidates, Path("unused"))
    second, _ = prepare.build_dataset(candidates, Path("unused"))

    assert first == second
    assert len(first) == 45
    assert {category: sum(row["category"] == category for row in first) for category in
            ("multi_hop", "single_hop", "unanswerable", "conflicting")} == {
                "multi_hop": 25, "single_hop": 5, "unanswerable": 8, "conflicting": 7,
            }
    original = {row["question_id"]: row["answer"] for row in candidates}
    for row in first:
        if row["category"] == "multi_hop":
            assert row["gold_answer"] == original[row["source_question_id"]]
            assert len({fact["title"] for fact in row["supporting_evidence"]}) >= 2
        if row["category"] == "conflicting":
            assert row["execution_mode"] == "fixture"


def test_final_dataset_rejects_changed_supporting_sentence(monkeypatch):
    candidates = prepare.read_jsonl(prepare.CANDIDATES)
    candidates[1]["supporting_evidence"][1]["sentence"] = "changed evidence"
    monkeypatch.setattr(prepare, "corpus_pairs", lambda _path: (_all_candidate_pairs(candidates), "hash"))
    with pytest.raises(ValueError, match="single-hop support"):
        prepare.build_dataset(candidates, Path("unused"))


def test_corpus_pair_builder_requires_exact_sentence_in_document(tmp_path):
    corpus = tmp_path / "corpus.jsonl"
    row = {
        "title": "Example", "text": "Unicode café fact. Another unsupported sentence.",
        "source_variants": [{"title": "Example", "sentences": ["Unicode café fact.", "missing sentence"]}],
    }
    corpus.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    pairs, digest = prepare.corpus_pairs(corpus)

    assert ("example", "unicode café fact.") in pairs
    assert ("example", "missing sentence") not in pairs
    assert len(digest) == 64


def test_corpus_pair_builder_rejects_unanswerable_identifier_in_metadata(tmp_path):
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(json.dumps({"title": "QX-EMBER-7719", "text": "ordinary text", "source_variants": []}) + "\n",
                      encoding="utf-8")
    with pytest.raises(ValueError, match="identifier unexpectedly occurs"):
        prepare.corpus_pairs(corpus)


def test_answer_span_match_and_case_quality_count_abstention_correctly():
    assert answer_span_match("May 3, 1977", "Tyronn Lue was born on May 3, 1977.")
    assert not answer_span_match("May 3, 1977", "Tyronn Lue was born on May 4, 1977.")
    answered = {
        "status": "answered", "central_claim_id": "c1",
        "claims": [{"claim_id": "c1", "text": "The paper appeared in 1957.", "citations": []}],
        "trace": {"evidence_diagnostic": {"draft_citation_count": 1,
                                            "verified_citation_count": 1,
                                            "rejected_claim_count": 0}},
    }
    case = {"expected_status": "answered", "gold_answer": "1957"}
    scored = case_quality(case, answered)
    assert scored["answer_correctness"] is True
    assert scored["citation_validity"] == 1.0
    abstention = case_quality({"expected_status": "insufficient", "gold_answer": ""},
                              {"status": "insufficient", "claims": [], "trace": {}})
    assert abstention["answer_correctness"] is True


def test_failure_categories_separate_retrieval_abstention_reasoning_and_citations():
    case = {"category": "multi_hop", "expected_status": "answered"}
    quality = {"predicted_status": "insufficient", "evidence_diagnostic": "model_abstained"}
    assert _failure_categories(case, quality, {"coverage": 0.5}, {}, None) == ["retrieval_miss"]
    assert _failure_categories(case, quality, {"coverage": 1.0}, {}, None) == ["model_abstention"]
    wrong_answer = {"predicted_status": "answered", "answer_correctness": False,
                    "draft_citation_count": 1, "evidence_diagnostic": "citations_verified"}
    assert _failure_categories(case, wrong_answer, {"coverage": 1.0}, {}, None) == [
        "incorrect_multi_hop_reasoning",
    ]
    invalid = {**wrong_answer, "evidence_diagnostic": "citation_rejected"}
    assert _failure_categories(case, invalid, {"coverage": 1.0}, {}, None) == [
        "invalid_or_missing_citation", "incorrect_multi_hop_reasoning",
    ]


def test_report_renders_sanitized_failure_diagnostics(tmp_path):
    report = render_final_report(
        status="partial_budget_or_interruption",
        aggregate={"modes": {"semantic": {
            "failure_category_counts": {"retrieval_miss": 1},
            "sanitized_failure_examples": [{
                "case_id": "case-1", "category": "multi_hop",
                "question": "Which report describes the delay?",
                "predicted_status": "insufficient",
                "failure_categories": ["retrieval_miss"],
                "evidence_diagnostic": "model_abstained",
                "supporting_references_retrieved": 1,
                "supporting_references_total": 2,
            }],
        }}, "fixture_conflicts": {}},
        completed_cases=1, planned_investigations=121,
        results_path=tmp_path / "ignored-results.jsonl", dataset_sha256="dataset-hash",
        daily_budget=0,
    )

    assert "case-1" in report
    assert "retrieval_miss" in report
    assert "1/2 support references" in report
    assert "Which report describes the delay?" in report


def test_evidence_coverage_requires_matching_title_and_sentence():
    fact = [{"title": "Maile Meloy", "sentence": "Born January 1, 1972."}]
    hit = {"title": "Maile Meloy", "evidence_text": "Born January 1, 1972."}
    assert evidence_coverage(fact, [hit])["coverage"] == 1.0
    assert evidence_coverage(fact, [{**hit, "title": "Different title"}])["coverage"] == 0.0
    assert evidence_coverage([], []) is None


def test_final_live_gate_requires_complete_frankfurt_indexed_evidence():
    cases = [
        {"category": "single_hop", "supporting_evidence": [{"title": "T", "sentence": "A."}]},
        {"category": "unanswerable", "supporting_evidence": []},
    ]
    coverage = {
        "project_ref": "nldnpqhqrfwjgxcqeuru", "indexed_documents": 50_000,
        "eligible_cases": 1, "supporting_sentence_references_found": 1,
    }
    require_complete_indexed_coverage(cases, coverage)

    with pytest.raises(RuntimeError, match="approved Frankfurt"):
        require_complete_indexed_coverage(cases, {**coverage, "project_ref": "other-project"})
    with pytest.raises(RuntimeError, match="50,000-document"):
        require_complete_indexed_coverage(cases, {**coverage, "indexed_documents": 49_999})
    with pytest.raises(RuntimeError, match="not every answerable"):
        require_complete_indexed_coverage(cases, {**coverage, "eligible_cases": 0})
    with pytest.raises(RuntimeError, match="support-reference count"):
        require_complete_indexed_coverage(cases, {**coverage, "supporting_sentence_references_found": 0})


def test_indexed_coverage_query_reads_only_required_titles_and_documents():
    class Rows:
        def __init__(self, values):
            self.values = values

        def fetchall(self):
            return self.values

    class Connection:
        def __init__(self):
            self.calls = []

        def execute(self, query, params):
            self.calls.append((query, params))
            if "FROM public.document_sources" in query:
                return Rows([
                    ("source-1", "doc-1", "example title", ["Known   fact.", "Unneeded sentence."]),
                    ("source-2", "doc-2", "example title", ["Different fact."]),
                    ("source-3", "doc-3", "unrelated title", ["Known fact."]),
                ])
            assert "FROM public.chunks AS c" in query
            return Rows([("doc-1", "Context. Known fact. More context.")])

    conn = Connection()
    rows = read_indexed_source_evidence_for_references(conn, [
        {"title": "Example Title", "sentence": "KNOWN fact."},
    ])

    assert len(conn.calls) == 2
    assert conn.calls[0][1] == (["example title"],)
    assert conn.calls[1][1] == (["doc-1"],)
    pairs = indexed_evidence_pairs(rows)
    assert ("example title", "known fact.") in pairs
    assert all("Unneeded sentence." not in row["sentences"] for row in rows)


def _evaluation_plan_cases():
    cases = []
    for category, count in (("multi_hop", 25), ("single_hop", 5), ("unanswerable", 8)):
        for index in range(count):
            cases.append({
                "case_id": f"{category}-{index}",
                "category": category,
                "execution_mode": "live",
                "source_question_id": f"final-only-{category}-{index}",
            })
    for index in range(7):
        cases.append({
            "case_id": f"conflicting-{index}", "category": "conflicting",
            "execution_mode": "fixture",
        })
    return cases


def test_economical_and_full_evaluation_plans_preserve_expected_request_caps():
    cases = _evaluation_plan_cases()
    economical = audit_plan(
        cases, dataset_sha256="final-dataset", daily_budget=0,
        comparison_plan="economical",
    )
    full = audit_plan(
        cases, dataset_sha256="final-dataset", daily_budget=0,
        comparison_plan="full",
    )

    assert economical["planned_investigations_for_final_comparison"] == 45
    assert economical["max_gemini_http_requests_for_final_comparison"] == 225
    assert economical["answer_generation_modes"] == ["semantic"]
    assert full["planned_investigations_for_final_comparison"] == 121
    assert full["max_gemini_http_requests_for_final_comparison"] == 605
    assert full["answer_generation_modes"] == ["semantic", "keyword", "hybrid"]


def test_retrieval_only_cases_exclude_gold_answers_and_non_answerable_cases(monkeypatch, tmp_path):
    cases = [
        {
            "case_id": f"answer-{index}", "category": "multi_hop",
            "execution_mode": "live", "expected_status": "answered",
            "question": f"Question {index}?", "gold_answer": "private gold",
            "supporting_evidence": [{"title": "T", "sentence": "Fact."}],
        }
        for index in range(30)
    ] + [
        {"case_id": "no-answer", "expected_status": "insufficient", "execution_mode": "live"},
        {"case_id": "fixture", "expected_status": "conflicting", "execution_mode": "fixture"},
    ]
    answerable = evaluate_final._answerable_live_cases(cases)
    assert len(answerable) == 30
    assert all("gold_answer" not in case for case in answerable)

    observed = {}

    def fake_run_evaluation(**kwargs):
        observed.update(kwargs)
        return {"status": "passed", "eligible_questions": 30}

    monkeypatch.setattr("scripts.evaluate_retrieval.run_evaluation", fake_run_evaluation)
    result = evaluate_final._run_retrieval_only_comparison(
        cases, dataset_sha="final-dataset", details_path=tmp_path / "nested" / "retrieval.json",
    )

    assert result["eligible_questions"] == 30
    assert observed["require_all_eligible"] is True
    assert observed["dataset_sha256"] == "final-dataset"
    assert observed["top_k"] == 10 and observed["candidate_k"] == 20
    assert observed["semantic_weight"] == observed["keyword_weight"] == 1.0
    assert observed["rrf_k"] == 60
    assert len(observed["question_rows"]) == 30
    assert all("gold_answer" not in case for case in observed["question_rows"])


def test_retrieval_evaluation_can_fail_closed_on_an_unexpected_corpus_count(monkeypatch):
    import scripts.evaluate_retrieval as retrieval_eval

    class Result:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return (self.value,)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, _params=None):
            if "SELECT count(*) FROM public.documents" in query:
                return Result(49_999)
            assert "SET statement_timeout" in query
            return Result(None)

    monkeypatch.setattr(retrieval_eval, "connect_database", lambda **_kwargs: Connection())
    monkeypatch.setattr(retrieval_eval, "read_indexed_source_evidence_for_references", lambda *_args: [])
    monkeypatch.setattr(
        retrieval_eval, "load_model",
        lambda *_args, **_kwargs: pytest.fail("model must not load for a wrong corpus count"),
    )

    with pytest.raises(RuntimeError, match="expected 50000 indexed documents"):
        retrieval_eval.run_evaluation(
            question_rows=[{
                "question_id": "case", "question": "Q?",
                "supporting_evidence": [{"title": "T", "sentence": "S."}],
            }],
            expected_indexed_documents=50_000,
        )


def test_economical_final_report_does_not_label_retrieval_only_modes_as_answer_scores(tmp_path):
    report = render_final_report(
        status="prepared_live_evaluation_pending", aggregate={
            "modes": {
                "semantic": {"completed_live_cases": 0},
                "keyword": {"answer_correct_cases": 99},
                "hybrid": {"answer_correct_cases": 99},
            },
            "fixture_conflicts": {},
        }, completed_cases=0, planned_investigations=45,
        results_path=tmp_path / "results.jsonl", comparison_plan="economical",
        answer_generation_modes=("semantic",), retrieval_comparison={
            "metrics": {mode: {"question_count": 30} for mode in ("semantic", "keyword", "hybrid")},
        },
    )
    answer_section = report.split("## Agent answer quality and safety metrics", 1)[1]
    answer_section = answer_section.split("## Metric definitions", 1)[0]

    assert "| Semantic |" in answer_section
    assert "| Keyword |" not in answer_section
    assert "| Hybrid |" not in answer_section
    assert "45 investigations" in report
    assert "maximum 225 Gemini HTTP requests" in report


def test_ranked_hits_deduplicate_by_first_tool_occurrence():
    hits = [
        {"chunk_id": "c1", "doc_id": "d1", "title": "A", "titles": ["A"], "rank": 2, "tool_call_index": 1},
        {"chunk_id": "c1", "doc_id": "d1", "title": "A", "titles": ["A"], "rank": 1, "tool_call_index": 2},
        {"chunk_id": "c2", "doc_id": "d2", "title": "B", "titles": ["B"], "rank": 1, "tool_call_index": 2},
    ]
    assert [row["chunk_id"] for row in _ranked_unique_hits(hits)] == ["c1", "c2"]


def test_budget_ledger_is_rolling_and_never_reserves_over_limit(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    assert reserve_investigation(ledger, run_key="a", case_id="c1", mode="semantic", daily_budget=1)
    assert not reserve_investigation(ledger, run_key="b", case_id="c2", mode="semantic", daily_budget=1)
    assert len(_recent_reservations(ledger)) == 1


def test_result_checkpoint_recovery_preserves_complete_rows_and_drops_partial_tail(tmp_path):
    results = tmp_path / "results.jsonl"
    complete = json.dumps({"run_key": "done"}) + "\n"
    results.write_bytes((complete + '{"run_key":"interrupted').encode("utf-8"))

    _repair_incomplete_result_tail(results)

    assert results.read_text(encoding="utf-8") == complete


def test_result_checkpoint_recovery_adds_newline_to_complete_tail(tmp_path):
    results = tmp_path / "results.jsonl"
    results.write_text('{"run_key":"done"}', encoding="utf-8")

    _repair_incomplete_result_tail(results)

    assert results.read_text(encoding="utf-8") == '{"run_key":"done"}\n'


def test_interrupted_reservation_is_not_retried_after_daily_window(tmp_path, monkeypatch):
    import datetime
    import app.evaluation.final_runner as runner

    case = {"case_id": "case-1", "category": "single_hop", "execution_mode": "live",
            "question": "Question?", "gold_answer": "answer", "expected_status": "answered",
            "supporting_evidence": [{"title": "T", "sentence": "A."}]}
    settings = Settings(
        database_url="postgresql://user:pass@db.nldnpqhqrfwjgxcqeuru.supabase.co/postgres",
        gemini_api_key="test-key", investigation_daily_budget=2,
    )
    dataset_sha, model_name = "dataset", "gemini-3.5-flash-lite"
    run_key = build_run_key(case["case_id"], "semantic", dataset_sha, model_name)
    old_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)).isoformat()
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"reserved_at": old_time, "run_key": run_key}) + "\n", encoding="utf-8")
    monkeypatch.setattr("app.evaluation.final_runner.load_model", lambda *_args, **_kwargs: pytest.fail("must not retry"))

    outcome = run_live(
        cases=[case], modes=("semantic",), dataset_sha256=dataset_sha, settings=settings,
        results_path=tmp_path / "results.jsonl", ledger_path=ledger,
    )
    assert outcome["status"] == "no_pending_cases"
    assert outcome["uncertain_inflight"] == 1


def test_live_runner_fails_closed_when_daily_budget_is_zero(tmp_path, monkeypatch):
    settings = Settings(
        database_url="postgresql://user:pass@db.nldnpqhqrfwjgxcqeuru.supabase.co/postgres",
        gemini_api_key="test-key", investigation_daily_budget=0,
    )
    monkeypatch.setattr("app.evaluation.final_runner.load_model", lambda *_args, **_kwargs: pytest.fail("model must not load"))
    with pytest.raises(RuntimeError, match="BUDGET is 0"):
        run_live(cases=[], modes=("semantic",), dataset_sha256="hash", settings=settings,
                 results_path=tmp_path / "results.jsonl", ledger_path=tmp_path / "ledger.jsonl")


def test_live_runner_checkpoints_and_does_not_repeat_completed_call(tmp_path, monkeypatch):
    import app.evaluation.final_runner as runner

    case = {
        "case_id": "single-1", "category": "single_hop", "execution_mode": "live",
        "question": "When was it published?", "gold_answer": "1957",
        "expected_status": "answered",
        "supporting_evidence": [{"title": "Paper", "sentence": "Published in 1957."}],
    }
    settings = Settings(
        database_url="postgresql://user:pass@db.nldnpqhqrfwjgxcqeuru.supabase.co/postgres",
        gemini_api_key="test-key", gemini_model="gemini-3.5-flash-lite",
        investigation_daily_budget=2,
    )
    calls = []
    raw = {
        "status": "answered", "answer": "It appeared in 1957.", "central_claim_id": "c1",
        "claims": [{"claim_id": "c1", "text": "The paper appeared in 1957.", "citations": []}],
        "trace": {
            "tool_calls": [{"tool": "search_evidence"}],
            "api_usage": {"request_count": 3, "request_latencies_seconds": [0.1, 0.1, 0.1]},
            "total_investigation_seconds": 0.5,
            "evidence_diagnostic": {"outcome": "citations_verified", "draft_citation_count": 1,
                                    "verified_citation_count": 1, "rejected_claim_count": 0},
            "evaluation_retrieval_results": [{
                "chunk_id": "chunk-1", "doc_id": "doc-1", "title": "Paper", "titles": ["Paper"],
                "score": 0.8, "rank": 1, "tool_call_index": 1,
                "evidence_text": "Published in 1957.",
            }],
        },
    }

    def fake_run(question, **kwargs):
        calls.append((question, kwargs))
        return raw

    monkeypatch.setattr(runner, "load_model", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(runner, "run_investigation", fake_run)
    results, ledger = tmp_path / "results.jsonl", tmp_path / "ledger.jsonl"
    first = run_live(cases=[case], modes=("semantic",), dataset_sha256="dataset-hash",
                     settings=settings, results_path=results, ledger_path=ledger)
    second = run_live(cases=[case], modes=("semantic",), dataset_sha256="dataset-hash",
                      settings=settings, results_path=results, ledger_path=ledger)

    assert first["completed_this_run"] == 1
    assert second["status"] == "no_pending_cases"
    assert len(calls) == 1
    assert calls[0][0] == case["question"]
    assert set(calls[0][1]) == {"settings", "model", "retrieval_mode", "capture_evaluation_details"}
    saved = json.loads(results.read_text(encoding="utf-8"))
    assert saved["supporting_evidence_coverage"]["coverage"] == 1.0
    assert "Published in 1957." not in json.dumps(saved)
    assert saved["api_request_count"] == 3
    assert saved["retrieval_ranking_for_metrics"][0]["investigation_rank"] == 1
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1


def test_failed_result_keeps_sanitized_error_reason():
    case = {"case_id": "case", "category": "unanswerable", "execution_mode": "live",
            "question": "Question?", "gold_answer": "Insufficient", "expected_status": "insufficient",
            "supporting_evidence": []}
    row = make_case_result(case, mode="semantic", raw_result=None,
                           dataset_sha256="hash", model="gemini-3.5-flash-lite",
                           error_type="OperationalError")
    assert row["abstention_or_error_reason"] == "OperationalError"
    assert row["api_request_count"] is None


def test_agent_can_capture_private_evaluation_rankings_without_public_trace(monkeypatch):
    import app.llm.tools as tools
    from app.api.investigations import _public_result

    sentence = "A change delayed payment processing by 12 minutes."
    hit = {
        "chunk_id": "chunk-1", "doc_id": "doc-1", "title": "Incident Report",
        "titles": ["Incident Report"], "sources": [{"source_id": "src-1", "title_alias": "Incident Report"}],
        "evidence_text": sentence,
        "validation_source": {"full_text": sentence, "start_char": 0, "end_char": len(sentence)},
        "score": 0.8,
    }
    monkeypatch.setattr(tools, "search", lambda *_args, **_kwargs: pytest.fail("injected search should be used"))
    responses = iter([
        LLMResponse(None, [FunctionCall("search_evidence", {"query": "focused evidence"})], {"parts": []}, [], {}),
        LLMResponse("Ready", [], {"parts": []}, [], {}),
        LLMResponse(json.dumps({
            "central_claim_id": "c1", "claims": [{"claim_id": "c1",
                "text": "A change delayed payment processing.", "citations": [
                    {"chunk_id": "chunk-1", "quote": sentence},
                ]}], "conflict_groups": [],
        }), [], {"parts": []}, [], {}),
    ])
    llm = type("LLM", (), {
        "settings": type("Cfg", (), {"gemini_model": "gemini-3.5-flash-lite"})(),
        "generate": lambda self, *args, **kwargs: next(responses),
    })()
    result = investigate(
        "Why was processing delayed?", conn=object(), embedding_model=None,
        llm_client=llm, capture_evaluation_details=True,
        search_function=lambda *_args, **_kwargs: [hit],
    ).as_dict()
    assert result["trace"]["evaluation_retrieval_results"][0]["rank"] == 1
    assert result["trace"]["evaluation_retrieval_results"][0]["evidence_text"] == sentence
    public = _public_result(result)
    assert "trace" not in public
    assert "evaluation_retrieval_results" not in json.dumps(public)

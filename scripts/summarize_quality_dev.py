"""Summarize the completed independent comparison without new model calls."""

from collections import Counter
import json

from app.config import Settings
from app.evaluation.final_runner import DEFAULT_LEDGER, _all_reservations, read_jsonl, sha256_file
from app.evaluation.quality_baseline import baseline_source
from app.evaluation.quality_dev import ROOT, load_cases, summarize


def main():
    cases, _ = load_cases()
    expected = {c["case_id"]: c for c in cases}
    variants = {}
    summaries = {}
    for variant in ("before", "after"):
        path = ROOT / f"reports/quality_dev_{variant}_results.jsonl"
        rows = read_jsonl(path)
        if len(rows) != 30 or {r["case_id"] for r in rows} != set(expected):
            raise RuntimeError("comparison is incomplete or includes unexpected cases")
        if any(not 0 <= r["api_request_count"] <= 5 for r in rows):
            raise RuntimeError("per-investigation request cap violated")
        if any(r["expected_answer"] != expected[r["case_id"]]["gold_answer"] for r in rows):
            raise RuntimeError("development gold mismatch")
        variants[variant] = {r["case_id"]: r for r in rows}
        summaries[variant] = {
            **summarize(rows, cases), "checkpoint_sha256": sha256_file(path),
            "quote_check_counts": dict(Counter(
                c["outcome"] for r in rows for c in r["private_evaluation_details"].get(
                    "evaluation_validation_details", {}).get("citation_checks", []))),
        }
    requests = sum(s["api_requests"] for s in summaries.values())
    if requests > 300:
        raise RuntimeError("authorized request ceiling exceeded")
    before, candidate = variants["before"], variants["after"]
    dev_ids = [c["case_id"] for c in cases if c["execution_mode"] == "live"]
    retained = json.loads((ROOT / "reports/quality_dev_retained_replay.json").read_text(encoding="utf-8"))
    if retained["baseline_result_sha256"] != summaries["before"]["checkpoint_sha256"]:
        raise RuntimeError("retained replay uses a different baseline checkpoint")
    output = {
        "scope": "independent development comparison; no final-set rerun",
        "live_investigations": 60, "live_gemini_requests": requests,
        "frozen_baseline_live": summaries["before"],
        "prompt_candidate_live_not_selected": summaries["after"],
        "retained_validator_saved_draft_replay": retained,
        "dev_span_score_improvements": [k for k in dev_ids if not before[k]["answer_correctness"]
                                         and candidate[k]["answer_correctness"]],
        "dev_span_score_regressions": [k for k in dev_ids if before[k]["answer_correctness"]
                                        and not candidate[k]["answer_correctness"]],
        "local_budget_after_process_restore": Settings.load().investigation_daily_budget,
        "ledger_reservations_total": len(_all_reservations(DEFAULT_LEDGER)),
        "runtime_prompt_support_equals_baseline": (ROOT / "app/llm/agent_support.py").read_text(
            encoding="utf-8").replace("\r\n", "\n") == baseline_source("app/llm/agent_support.py"),
    }
    (ROOT / "reports/quality_dev_comparison.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"investigations": 60, "requests": requests,
                      "budget_after_restore": output["local_budget_after_process_restore"],
                      "ledger_reservations": output["ledger_reservations_total"]}))


if __name__ == "__main__":
    main()

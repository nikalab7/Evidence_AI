"""Audit or run the budget-gated final answer evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import psycopg

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.llm.schemas import MAX_LLM_REQUESTS
from app.evaluation.final_runner import (
    DEFAULT_LEDGER, DEFAULT_REPORT, DEFAULT_RESULTS, DEV_CASES, FINAL_CASES, MODES,
    audit_plan, check_indexed_coverage, read_jsonl,
    require_complete_indexed_coverage,
    run_live, sha256_file,
)
from app.evaluation.reporting import render_final_report


def _offline_audit(cases: list[dict[str, Any]], dataset_sha: str, settings: Settings) -> dict[str, Any]:
    plan = audit_plan(cases, dataset_sha256=dataset_sha, daily_budget=settings.investigation_daily_budget)
    candidate_path = ROOT / "eval" / "eval_candidates.jsonl"
    dev_path = ROOT / "eval" / "retrieval_dev.jsonl"
    data_path = ROOT / "data" / "corpus.jsonl"
    plan["candidate_pool_sha256"] = sha256_file(candidate_path)
    plan["retrieval_dev_sha256"] = sha256_file(dev_path)
    plan["corpus_available_for_regeneration"] = data_path.exists()
    if data_path.exists():
        from scripts.prepare_final_eval import build_dataset

        regenerated, summary = build_dataset(read_jsonl(candidate_path), data_path)
        if regenerated != cases:
            raise ValueError("committed final evaluation file differs from deterministic regeneration")
        plan["offline_corpus_support_check"] = {
            "status": "passed", "supporting_references": summary["answerable_support_references"],
            "coverage_percent": summary["local_corpus_support_coverage_percent"],
            "corpus_sha256": summary["corpus_jsonl_sha256"],
        }
    else:
        plan["offline_corpus_support_check"] = {
            "status": "not_run", "reason": "data/corpus.jsonl is locally generated and Git-ignored",
        }
    plan["api_usage_estimate"] = {
        "final_investigations": plan["planned_investigations_for_final_comparison"],
        "final_max_http_requests": plan["max_gemini_http_requests_for_final_comparison"],
        "historical_planning_range_http_requests": [
            plan["planned_investigations_for_final_comparison"] * 3,
            plan["max_gemini_http_requests_for_final_comparison"],
        ],
        "historical_sample_basis": "two Phase 3 investigations used 3 and 5 Gemini HTTP requests; too small to predict actual final usage",
        "additional_development_smoke": {"investigations": 1, "max_http_requests": 5},
        "daily_budget_note": "local setting only; Render sync:false value and provider quota are not visible here",
    }
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--live", action="store_true", help="allow actual Gemini investigations")
    action.add_argument("--check-indexed-coverage", action="store_true", help="read-only Frankfurt evidence-coverage check")
    parser.add_argument("--final", action="store_true", help="run the final cases (requires --live and --confirm-api-usage)")
    parser.add_argument("--dev-smoke", action="store_true", help="run one retrieval-development question (requires --live)")
    parser.add_argument("--confirm-api-usage", action="store_true", help="confirm the printed Gemini request estimate")
    parser.add_argument("--max-investigations", type=int, help="cap this invocation; completed cases are checkpointed")
    parser.add_argument("--modes", default=",".join(MODES), help="comma-separated retrieval modes")
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--cases", type=Path, default=FINAL_CASES)
    parser.add_argument("--dev", type=Path, default=DEV_CASES)
    args = parser.parse_args()
    try:
        settings = Settings.load()
        cases = read_jsonl(args.cases)
        dataset_sha = sha256_file(args.cases)
        final_plan: dict[str, Any] | None = None
        if args.check_indexed_coverage:
            report = check_indexed_coverage(cases)
            print(json.dumps({"status": "passed", **report}, sort_keys=True))
            return 0
        if not args.live:
            report = _offline_audit(cases, dataset_sha, settings)
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            return 0
        if args.final == args.dev_smoke:
            raise ValueError("choose exactly one of --final or --dev-smoke with --live")
        if not args.confirm_api_usage:
            raise ValueError("live calls require --confirm-api-usage after reviewing the request estimate")
        modes = tuple(item.strip() for item in args.modes.split(",") if item.strip())
        if args.final:
            if set(modes) != set(MODES):
                raise ValueError("final comparison requires the same complete semantic,keyword,hybrid mode set")
            final_plan = _offline_audit(cases, dataset_sha, settings)
            corpus_check = final_plan["offline_corpus_support_check"]
            if corpus_check.get("status") != "passed":
                raise RuntimeError("final live run requires a passing local corpus and gold-evidence audit")
            planned = final_plan["planned_investigations_for_final_comparison"]
            print(json.dumps({
                "preflight": "live final evaluation", "cases": len(cases),
                "planned_investigations": planned,
                "maximum_gemini_http_requests": planned * MAX_LLM_REQUESTS,
                "local_daily_budget": settings.investigation_daily_budget,
                "model": settings.gemini_model or "gemini-3.5-flash-lite",
                "dataset_sha256": dataset_sha,
                "local_corpus_evidence_check": corpus_check,
            }, sort_keys=True), flush=True)
            if settings.investigation_daily_budget <= 0:
                raise RuntimeError("local INVESTIGATION_DAILY_BUDGET is 0; live evaluation is disabled")
            if not settings.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY is not configured")
            indexed_coverage = check_indexed_coverage(cases)
            require_complete_indexed_coverage(cases, indexed_coverage)
            print(json.dumps({"preflight": "indexed evidence verified", **indexed_coverage}, sort_keys=True),
                  flush=True)
        else:
            dev = read_jsonl(args.dev)
            if not dev:
                raise ValueError("retrieval development file has no questions")
            question = dev[0]
            cases = [{
                "case_id": f"dev-smoke-{question['question_id']}",
                "category": "development_smoke", "execution_mode": "live",
                "question": question["question"], "gold_answer": "",
                "expected_status": "not_scored", "supporting_evidence": [],
            }]
            modes = ("semantic",)
            dataset_sha = hashlib.sha256(args.dev.read_bytes()).hexdigest()
            if args.results == DEFAULT_RESULTS:
                args.results = ROOT / "reports" / "final_evaluation_smoke.jsonl"
            print(json.dumps({
                "preflight": "one retrieval-development smoke investigation",
                "investigations": 1, "maximum_gemini_http_requests": MAX_LLM_REQUESTS,
                "model": settings.gemini_model or "gemini-3.5-flash-lite",
            }, sort_keys=True), flush=True)
        report = run_live(
            cases=cases, modes=modes, dataset_sha256=dataset_sha,
            settings=settings, results_path=args.results, ledger_path=args.ledger,
            max_investigations=args.max_investigations,
        )
        if args.final:
            plan = final_plan or audit_plan(
                cases, dataset_sha256=dataset_sha,
                daily_budget=settings.investigation_daily_budget,
            )
            aggregate = report.get("aggregate", {})
            complete = (
                all(aggregate.get("modes", {}).get(mode, {}).get("completed_live_cases") == 38
                    for mode in MODES)
                and aggregate.get("fixture_conflicts", {}).get("completed") == 7
            )
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(render_final_report(
                status="complete" if complete else "partial_budget_or_interruption",
                aggregate=aggregate,
                completed_cases=report.get("completed_total", 0),
                planned_investigations=plan["planned_investigations_for_final_comparison"],
                results_path=args.results,
                dataset_sha256=dataset_sha,
                daily_budget=settings.investigation_daily_budget,
            ), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        report = {"status": "blocked_or_failed", "error_type": type(exc).__name__}
        if isinstance(exc, psycopg.Error):
            report["sqlstate"] = exc.sqlstate
            report["message"] = "read-only database check failed; connection details were suppressed"
        else:
            report["message"] = str(exc)
        print(json.dumps(report, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

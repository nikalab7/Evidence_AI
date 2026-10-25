"""Offline validator replay or explicitly authorized development-only Gemini run."""

import argparse
from collections import Counter
import json
from time import perf_counter
import statistics

from app.config import Settings
from app.evaluation.final_runner import DEFAULT_LEDGER, _fixture_search, _recent_reservations
from app.evaluation.quality_baseline import BASELINE_COMMIT, baseline_validator
from app.evaluation.quality_dev import ROOT, load_cases
from app.reasoning.citations import validate_final_response


def replay(fixtures):
    results = {}
    for variant, validator in (("before", baseline_validator()), ("after", validate_final_response)):
        rows = []
        timings = []
        for case in fixtures:
            hits = _fixture_search(case)(None, "fixture", limit=32)
            evidence = {h["chunk_id"]: h for h in hits}
            for _ in range(25):
                started = perf_counter()
                output = validator(case["replay_draft"], evidence)
                timings.append((perf_counter() - started) * 1000)
            rows.append({"case_id": case["case_id"], "expected": case["expected_status"],
                         "predicted": output["status"],
                         "citations_retained": sum(len(c["citations"]) for c in output["claims"])})
        positives = [r for r in rows if r["expected"] == "conflicting"]
        negatives = [r for r in rows if r["expected"] != "conflicting"]
        results[variant] = {
            "conflict_correct": sum(r["predicted"] == "conflicting" for r in positives),
            "conflict_denominator": len(positives),
            "false_conflicts": sum(r["predicted"] == "conflicting" for r in negatives),
            "control_denominator": len(negatives),
            "correct_controls": sum(r["predicted"] == r["expected"] for r in negatives),
            "retained_citations": sum(r["citations_retained"] for r in rows),
            "median_validator_ms": statistics.median(timings), "rows": rows,
        }
    return {"scope": "scripted response replay; tests validator acceptance, NOT model accuracy or retrieval",
            "baseline_commit": BASELINE_COMMIT, "gemini_requests": 0, "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--variant", choices=("before", "after"))
    parser.add_argument("--confirm-api-usage", action="store_true")
    parser.add_argument("--max-investigations", type=int, default=30)
    args = parser.parse_args()
    cases, manifest = load_cases()
    if args.live:
        if not args.confirm_api_usage or not args.variant:
            parser.error("live development calls require --variant and --confirm-api-usage")
        from app.evaluation.quality_live import run_live_comparison
        try:
            output = run_live_comparison(cases, variant=args.variant, settings=Settings.load(),
                                         max_investigations=args.max_investigations)
        except Exception as exc:
            print(json.dumps({"status": "blocked_or_failed", "error_type": type(exc).__name__}))
            return 2
        (ROOT / f"reports/quality_dev_{args.variant}_summary.json").write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif args.plan:
        settings = Settings.load()
        output = {
            "cases_per_variant": len(cases), "baseline_plus_current_investigations": 2 * len(cases),
            "maximum_http_requests": 10 * len(cases),
            "current_local_budget": settings.investigation_daily_budget,
            "recent_reservations": len(_recent_reservations(DEFAULT_LEDGER)),
            "development_questions": len(manifest["selected_ids"]),
            "fixture_statuses": dict(Counter(c["expected_status"] for c in cases if c["execution_mode"] == "fixture")),
            "live_execution": "requires separate operator approval; no final cases will be rerun",
        }
    else:
        output = replay([c for c in cases if c["execution_mode"] == "fixture"])
        (ROOT / "reports/quality_dev_replay.json").write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(output, sort_keys=True))
    return 2 if output.get("stop_reason") else 0


if __name__ == "__main__":
    raise SystemExit(main())

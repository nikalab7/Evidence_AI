"""Independent development inputs and scoring; never load the final gold set."""

import hashlib
import json
import math
from pathlib import Path
import statistics

from app.evaluation.final_runner import read_jsonl, sha256_file

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "eval/quality_dev_manifest.json"
FIXTURES = ROOT / "eval/quality_dev_fixtures.json"
QUESTIONS = ROOT / "eval/quality_dev_questions.jsonl"
CODE_PATHS = ("app/llm/agent.py", "app/llm/agent_support.py", "app/llm/tools.py",
              "app/llm/gemini_client.py", "app/llm/schemas.py", "app/reasoning/citations.py",
              "app/reasoning/citation_checks.py", "app/reasoning/contradictions.py")


def load_cases() -> tuple[list[dict], dict]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for path, key in ((QUESTIONS, "questions_sha256"), (FIXTURES, "fixtures_sha256"),
                      (ROOT / manifest["source"], "source_sha256")):
        if sha256_file(path) != manifest[key]:
            raise ValueError("development input hash mismatch")
    rows = read_jsonl(QUESTIONS)
    source = {r["question_id"]: r for r in read_jsonl(ROOT / manifest["source"])}
    if len(rows) != 20 or [r["question_id"] for r in rows] != manifest["selected_ids"]:
        raise ValueError("development selection mismatch")
    if any(source.get(r["question_id"]) != r for r in rows):
        raise ValueError("a development question or its gold answer was changed")
    cases = [{**r, "case_id": "dev-" + r["question_id"], "category": "multi_hop",
              "execution_mode": "live", "expected_status": "answered", "gold_answer": r["answer"]}
             for r in rows]
    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    if len(fixtures) != 10 or sum(c["expected_status"] == "conflicting" for c in fixtures) != 5:
        raise ValueError("expected five new contradictions and five controls")
    return cases + fixtures, manifest


def run_fingerprint(variant: str) -> str:
    from app.evaluation.quality_baseline import BASELINE_COMMIT
    payload = {"manifest": sha256_file(MANIFEST), "variant": variant,
               "baseline_commit": BASELINE_COMMIT,
               "harness": {path: sha256_file(ROOT / path) for path in (
                   "app/evaluation/quality_live.py", "app/evaluation/quality_baseline.py",
                   "app/evaluation/quality_dev.py", "app/evaluation/answer_metrics.py",
               )}}
    if variant == "after":
        payload["code"] = {path: sha256_file(ROOT / path) for path in CODE_PATHS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def summarize(rows: list[dict], cases: list[dict]) -> dict:
    by_id = {c["case_id"]: c for c in cases}
    conflicts = [r for r in rows if by_id[r["case_id"]]["expected_status"] == "conflicting"]
    controls = [r for r in rows if by_id[r["case_id"]]["execution_mode"] == "fixture"
                and by_id[r["case_id"]]["expected_status"] != "conflicting"]
    dev = [r for r in rows if by_id[r["case_id"]]["execution_mode"] == "live"]
    missing = [r for r in rows if by_id[r["case_id"]]["expected_status"] == "insufficient"]
    citations = sum(r.get("draft_citation_count") or 0 for r in rows)
    valid = sum(r.get("verified_citation_count") or 0 for r in rows)
    latencies = sorted(r["latency_seconds"] for r in rows if isinstance(r.get("latency_seconds"), (int, float)))
    negative = [r for r in rows if by_id[r["case_id"]]["expected_status"] != "conflicting"]
    return {
        "completed": len(rows), "planned": len(cases),
        "conflict_correct": sum(r.get("predicted_status") == "conflicting" for r in conflicts),
        "conflict_denominator": len(conflicts),
        "false_conflicts_on_controls": sum(r.get("predicted_status") == "conflicting" for r in controls),
        "control_denominator": len(controls),
        "false_conflicts_on_dev": sum(r.get("predicted_status") == "conflicting" for r in dev),
        "all_false_conflicts": sum(r.get("predicted_status") == "conflicting" for r in negative),
        "nonconflicting_denominator": len(negative),
        "correct_abstentions": sum(r.get("predicted_status") == "insufficient" for r in missing),
        "predicted_abstentions": sum(r.get("predicted_status") == "insufficient" for r in rows),
        "missing_evidence_denominator": len(missing),
        "dev_answer_span_correct": sum(r.get("answer_correctness") is True for r in dev),
        "dev_denominator": len(dev), "verified_citations": valid, "draft_citations": citations,
        "dev_support_references_found": sum((r.get("supporting_evidence_coverage") or {}).get(
            "support_references_retrieved", 0) for r in dev),
        "dev_support_references": sum((r.get("supporting_evidence_coverage") or {}).get(
            "support_references", 0) for r in dev),
        "citation_validity": valid / citations if citations else None,
        "api_requests": sum(r.get("api_request_count") or 0 for r in rows),
        "median_seconds": statistics.median(latencies) if latencies else None,
        "p95_seconds": latencies[math.ceil(.95 * len(latencies)) - 1] if latencies else None,
        "error_cases": sum(r.get("error_type") is not None for r in rows),
    }

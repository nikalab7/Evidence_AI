"""Read frozen final results; write a separate, content-minimal engineering audit."""

from collections import Counter
import json
from pathlib import Path

from app.evaluation.final_runner import read_jsonl, sha256_file

ROOT = Path(__file__).resolve().parents[1]


def diagnose(rows: list[dict]) -> dict:
    conflicts = [r for r in rows if r["category"] == "conflicting"]
    abstentions = [r for r in rows if r["expected_status"] == "answered"
                   and r["predicted_status"] == "insufficient"]
    rejected = [r for r in rows if (r.get("draft_citation_count") or 0)
                > (r.get("verified_citation_count") or 0)]
    classified = []
    for row in abstentions:
        coverage = (row.get("supporting_evidence_coverage") or {}).get("coverage", 0)
        reason = ("retrieval_miss" if coverage < 1 else
                  "citation_rejection" if row["evidence_diagnostic"] == "citation_rejected"
                  else "model_abstention_with_complete_support")
        classified.append({"case_id": row["case_id"], "reason": reason,
                           "coverage": coverage, "outcome": row["evidence_diagnostic"]})
    dhl = next(r for r in rows if r["case_id"] == "hotpotqa-5ab8efc75542991b5579f05f")
    return {
        "conflicts": [{k: r.get(k) for k in (
            "case_id", "predicted_status", "evidence_diagnostic", "draft_citation_count",
            "verified_citation_count", "supporting_evidence_coverage", "tool_call_count",
        )} for r in conflicts],
        "incorrect_abstentions": classified,
        "abstention_causes": dict(Counter(r["reason"] for r in classified)),
        "citation_loss_cases": [{
            "case_id": r["case_id"], "draft": r["draft_citation_count"],
            "retained": r["verified_citation_count"],
            "withheld_with_claim": r["draft_citation_count"] - r["verified_citation_count"],
            "exact_failure_reason": "not_recoverable_from_saved_checkpoint",
        } for r in rejected],
        "dhl": {
            "expected": dhl["expected_answer"], "predicted": dhl["predicted_answer"],
            "coverage": dhl["supporting_evidence_coverage"],
            "cited_titles": sorted({title for claim in dhl["predicted_claims"]
                                     for cite in claim["citations"] for title in cite["titles"]}),
            "finding": "answer omitted the business-partner relation and selected the parent instead",
        },
        "diagnostic_limits": [
            "Original draft conflict_groups, central_claim_id and rejected quotations were not saved.",
            "All six failed conflicts reached central_claim_unverified after both claims passed quotes.",
            "Group generation cannot be confirmed retrospectively; the validator exited before checking groups.",
            "Seven withheld citations across three atomic claims are not seven individually proven bad quotes.",
            "Paraphrase, attribution, truncation and fabricated IDs cannot be distinguished for those lost quotes.",
        ],
    }


def main() -> None:
    paths = ["eval/final_answer_eval.jsonl", "eval/final_answer_eval_manifest.json",
             "reports/final_evaluation.md", "reports/final_evaluation_results.jsonl",
             "reports/final_retrieval_comparison.json"]
    frozen = {path: sha256_file(ROOT / path) for path in paths}
    if frozen[paths[0]] != "d2663d7a8deaf573d8eaac508296a35dacbd4ea43512986a2b34b6ce9c0c0f5e":
        raise RuntimeError("final dataset hash differs from the frozen baseline")
    output = {"frozen_files": frozen, **diagnose(read_jsonl(ROOT / paths[3]))}
    destination = ROOT / "reports/phase7_4_diagnosis.json"
    if destination.exists():
        previous = json.loads(destination.read_text(encoding="utf-8"))
        if previous["frozen_files"] != frozen:
            raise RuntimeError("a frozen final-evaluation artifact changed; refusing to replace its audit")
    destination.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"conflicts": len(output["conflicts"]),
                      "abstentions": output["abstention_causes"],
                      "citation_loss_cases": len(output["citation_loss_cases"])}))


if __name__ == "__main__":
    main()

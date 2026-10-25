"""Replay actual development drafts through the retained fix without Gemini calls."""

import json
from time import perf_counter

from app.evaluation.final_runner import make_case_result, read_jsonl, sha256_file
from app.evaluation.quality_baseline import baseline_validator
from app.evaluation.quality_dev import ROOT, load_cases, summarize
from app.reasoning.citations import validate_final_response


def main():
    cases, _ = load_cases()
    by_id = {c["case_id"]: c for c in cases}
    path = ROOT / "reports/quality_dev_before_results.jsonl"
    rows = read_jsonl(path)
    if len(rows) != 30 or {r["case_id"] for r in rows} != set(by_id):
        raise RuntimeError("replay requires all 30 independent baseline development results")
    wanted_docs = {h["doc_id"] for r in rows if r["execution_mode"] == "live"
                   for h in r["private_evaluation_details"]["evaluation_retrieval_results"]}
    documents = {}
    with (ROOT / "data/corpus.jsonl").open(encoding="utf-8") as source:
        for line in source:
            doc = json.loads(line)
            if doc["doc_id"] in wanted_docs:
                documents[doc["doc_id"]] = doc["text"]
    baseline = baseline_validator()
    retained_rows, changed = [], []
    for row in rows:
        trace = row["private_evaluation_details"]
        draft = trace["evaluation_final_draft"]
        retrieved = {}
        for hit in trace["evaluation_retrieval_results"]:
            text = hit["evidence_text"]
            if row["execution_mode"] == "live" and documents.get(hit["doc_id"]) != text:
                raise RuntimeError("saved chunk does not equal its canonical corpus paragraph; refusing inferred offsets")
            retrieved[hit["chunk_id"]] = {
                **hit, "validation_source": {"full_text": text, "start_char": 0, "end_char": len(text)},
            }
        original = baseline(draft, retrieved)
        if (original["status"] != row["predicted_status"] or
                sum(len(c["citations"]) for c in original["claims"]) != row["verified_citation_count"]):
            raise RuntimeError("saved-source reconstruction did not reproduce the original validator output")
        started = perf_counter()
        revised = validate_final_response(draft, retrieved)
        elapsed = perf_counter() - started
        if revised["status"] != original["status"]:
            changed.append({"case_id": row["case_id"], "before": original["status"], "retained": revised["status"]})
        raw = {**revised, "trace": {
            "api_usage": {"request_count": 0}, "total_investigation_seconds": elapsed,
            "evaluation_retrieval_results": trace["evaluation_retrieval_results"],
            "evidence_diagnostic": {
                "draft_citation_count": row["draft_citation_count"],
                "verified_citation_count": sum(len(c["citations"]) for c in revised["claims"]),
                "rejected_claim_count": len(revised["dropped_claim_ids"]),
                "outcome": "saved_development_draft_replay",
            },
        }}
        retained_rows.append(make_case_result(by_id[row["case_id"]], mode="semantic", raw_result=raw,
                                              dataset_sha256=row["dataset_sha256"], model=row["model"]))
    output = {
        "scope": "saved development drafts only; original baseline outputs reproduced before applying retained validator",
        "baseline_result_sha256": sha256_file(path), "baseline_statuses_reproduced": len(rows),
        "retained_validator_sha256": sha256_file(ROOT / "app/reasoning/citations.py"),
        "timing_scope": "local validator replay, not end-to-end investigation latency",
        "new_gemini_requests": 0, "changed_statuses": changed,
        "summary": summarize(retained_rows, cases),
    }
    (ROOT / "reports/quality_dev_retained_replay.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()

"""Render reproducible answer-evaluation reports without inventing missing metrics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.llm.schemas import MAX_LLM_REQUESTS

MODES = ("semantic", "keyword", "hybrid")


def _format_rate(value: Any) -> str:
    return f"{value:.4f}" if isinstance(value, (int, float)) else "pending"


def _format_latency(summary: Any, key: str) -> str:
    if not isinstance(summary, dict) or not isinstance(summary.get(key), (int, float)):
        return "pending"
    return f"{summary[key] * 1000:.1f} ms"


def render_final_report(
    *, status: str, aggregate: dict[str, Any] | None,
    completed_cases: int, planned_investigations: int,
    results_path: Path, dataset_sha256: str = "pending",
    daily_budget: int = 0,
) -> str:
    """Render measured results without filling pending values with estimates."""
    aggregate = aggregate or {"modes": {}, "fixture_conflicts": {}}
    if completed_cases == 0:
        evaluation_note = "No full live answer evaluation has been run in the current workspace. Cells marked `pending` are intentionally unmeasured."
    elif status == "complete":
        evaluation_note = "All planned cases have result rows. Metrics below are measured results from this run."
    else:
        evaluation_note = "This is a checkpointed partial run. Metrics use only completed cases and are not final evaluation results."
    budget_note = (
        "The configured local value is 0 and live calls are disabled."
        if daily_budget == 0 else
        f"The configured local value is {daily_budget}; the local journal limits this CLI to that rolling-24-hour count."
    )
    lines = [
        "# Phase 7 — Final Evaluation & Quality Report", "",
        f"Evaluation status: **{status}**", "",
        evaluation_note, "",
        f"- Final dataset SHA-256: `{dataset_sha256}`.",
        "- Reproduction manifest: [`eval/final_answer_eval_manifest.json`](../eval/final_answer_eval_manifest.json); "
        "it records candidate and dev hashes, seed, quotas, selected IDs, and corpus hash.",
        "## Dataset and isolation", "",
        "- Final set: 45 cases: 25 multi-hop/cross-document HotpotQA cases, "
        "5 direct single-hop cases, 8 synthetic unanswerable cases, and 7 synthetic conflict fixtures.",
        "- The 38 live cases run through the production service path. The 7 conflict cases use "
        "injected synthetic evidence with the production agent and citation/conflict validator; "
        "they do not measure database retrieval.",
        "- The separate 200-question retrieval development set is used only for tuning and the "
        "one-question smoke option. Final gold answers are not sent to the agent.",
        "- Answerable support coverage for all 30 live answerable cases was checked against the "
        "local corpus during dataset construction. The 25 selected candidates and the five "
        "single-hop source facts are drawn from the prior indexed 40/40 candidate coverage check "
        "(92/92 support references). Before any final Gemini call, the CLI now repeats a read-only "
        "Frankfurt project, 50,000-document, and complete support-coverage preflight.",
        "- Synthetic unanswerable identifiers were checked absent from the local generated corpus. "
        "No synthetic conflict documents were written to Supabase.", "",
        "## Retrieval configuration comparison", "",
        "Final-run settings are the existing defaults: BGE-small, semantic/keyword/hybrid modes, "
        "OR full-text keyword retrieval, equal-weight hybrid RRF (1.0/1.0, k=60), agent tool limit 4, "
        "and maximum 5 Gemini HTTP requests per investigation. The metrics "
        "below will use the same 30 answerable cases per mode; unanswerable cases remain in "
        "answer-quality metrics but not Recall@K/MRR.", "",
        "| Mode | Recall@5 | Recall@10 | MRR | Median investigation | p95 investigation | Completed / 38 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode in MODES:
        summary = aggregate.get("modes", {}).get(mode, {})
        retrieval = summary.get("retrieval") or {}
        latency = summary.get("investigation_latency")
        lines.append(
            f"| {mode.title()} | {_format_rate(retrieval.get('recall@5'))} "
            f"| {_format_rate(retrieval.get('recall@10'))} | {_format_rate(retrieval.get('mrr'))} "
            f"| {_format_latency(latency, 'median_seconds')} "
            f"| {_format_latency(latency, 'p95_nearest_rank_seconds')} "
            f"| {summary.get('completed_live_cases', 0)} / 38 |"
        )
    lines += [
        "", "## Answer quality and safety metrics", "",
        "| Mode | Correct / completed | Answer-span match | Strict exact match | Answered accuracy | Abstention precision / recall | Citation validity | Retrieved support coverage |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode in MODES:
        summary = aggregate.get("modes", {}).get(mode, {})
        answered = summary.get("answer_correct_cases", 0)
        denominator = summary.get("overall_correctness_denominator", 0)
        abstention = f"{_format_rate(summary.get('abstention_precision'))} / {_format_rate(summary.get('abstention_recall'))}"
        lines.append(
            f"| {mode.title()} | {answered} / {denominator} "
            f"| {_format_rate(summary.get('answer_span_match_rate'))} "
            f"| {_format_rate(summary.get('strict_exact_match_rate'))} "
            f"| {_format_rate(summary.get('answered_question_accuracy'))} "
            f"| {abstention} | {_format_rate(summary.get('citation_validity'))} "
            f"| {_format_rate(summary.get('supporting_evidence_coverage'))} |"
        )
    for mode in MODES:
        counts = aggregate.get("modes", {}).get(mode, {}).get("predicted_status_counts", {})
        if counts:
            lines.append(
                f"- {mode.title()} status counts: answered {counts.get('answered', 0)}, "
                f"abstained {counts.get('insufficient', 0)}, conflicting {counts.get('conflicting', 0)}."
            )
    conflicts = aggregate.get("fixture_conflicts", {})
    lines += [
        "", "Conflict fixture result: "
        f"{conflicts.get('correct_conflict_detections', 0)} / {conflicts.get('completed', 0)} "
        "correct detections; pending unless the isolated Gemini fixture run completed.", "",
        "## Metric definitions", "",
        "- Retrieval Recall@5/10 and MRR are supporting-title metrics over deduplicated chunks "
        "returned by the investigation's search-tool calls in order, assigned a cumulative "
        "first-seen investigation rank. The denominator is the "
        "complete-support answerable cases actually completed for each mode.",
        "- Answer-span match is a normalized contiguous token match of the gold answer within the "
        "verified central claim. Strict exact match requires the normalized central claim to equal "
        "the gold answer. Both are automated string-match proxies, not entailment judgments.",
        "- Overall correctness counts correct abstentions for the 8 unanswerable cases and requires "
        "an `answered` status plus answer-span match for answerable cases. Predicted answer, "
        "abstention, and conflict statuses are also counted separately.",
        "- Citation validity is accepted citations divided by citations emitted in the model's "
        "draft. The existing validator checks retrieved chunk IDs and exact quote presence after "
        "whitespace normalization; it does not prove claim entailment.",
        "- Supporting evidence coverage is the fraction of gold title/sentence references whose "
        "title and normalized sentence occur in retrieved chunks.", "",
        "## API usage and checkpoint", "",
        f"- Final comparison plan: {planned_investigations} investigations; maximum "
        f"{planned_investigations * MAX_LLM_REQUESTS} Gemini HTTP requests. "
        "Historical Phase 3 examples used 3 and 5 requests each (only two observations), so "
        "363–605 requests is a rough planning range, not a prediction.",
        f"- Completed result rows: {completed_cases}. The runner fsyncs each investigation "
        "reservation and result. On resume, an incomplete final JSONL row is discarded while its "
        "reservation remains uncertain; requests without a result are not automatically retried.",
        f"- Local result/checkpoint file: `{results_path}` (Git-ignored).",
        f"- Local `INVESTIGATION_DAILY_BUDGET`: {daily_budget}; {budget_note} "
        "The Frankfurt Blueprint value is `sync: false`; its production value and Gemini provider "
        "quota were not accessible here. This CLI ledger only coordinates local evaluation runs; "
        "it is not a durable global cap shared with Render.", "",
        "## Historical retrieval-only reference (200-question dev set)", "",
        "These are previously measured Phase 6A retrieval results, not Phase 7 answer metrics "
        "and not a substitute for the pending final comparison.", "",
        "| Mode / variant | Recall@5 | Recall@10 | MRR | Median latency | p95 latency |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        "| Semantic | 0.8425 | 0.8775 | 0.927881 | 660.919 ms | 1,079.142 ms |",
        "| OR keyword baseline | 0.2350 | 0.3625 | 0.254454 | 1,572.944 ms | 8,821.469 ms |",
        "| Equal-weight hybrid baseline | 0.7475 | 0.8550 | 0.764548 | 2,245.356 ms | 9,756.986 ms |",
        "| Informative-term keyword (0.05) | 0.2950 | 0.4550 | 0.342272 | 272.986 ms | 1,642.982 ms |",
        "", "## Failure analysis", "",
    ]
    mode_summaries = aggregate.get("modes", {})
    has_failure_examples = any(
        summary.get("sanitized_failure_examples") for summary in mode_summaries.values()
    )
    if has_failure_examples:
        for mode in MODES:
            summary = mode_summaries.get(mode, {})
            counts = summary.get("failure_category_counts", {})
            if counts:
                lines.append(
                    f"- {mode.title()} diagnostic counts (categories may overlap): "
                    + ", ".join(f"{name} {count}" for name, count in counts.items()) + "."
                )
            for item in summary.get("sanitized_failure_examples", []):
                question = str(item["question"]).replace("\n", " ").replace("|", "\\|")
                total = item.get("supporting_references_total")
                refs = (f"{item['supporting_references_retrieved']}/{total} support references"
                        if total is not None else "no gold support refs")
                lines.append(
                    f"- `{mode}` `{item['case_id']}` ({item['category']}): '{question}' - "
                    f"{', '.join(item['failure_categories'])}; status `{item.get('predicted_status')}`; "
                    f"{refs}; validator diagnostic `{item.get('evidence_diagnostic')}`."
                )
    else:
        lines.append(
            "No Phase 7 live failure examples exist yet. After an approved run, the report will "
            "include sanitized case IDs, questions, failure labels, support-reference coverage, "
            "and validator diagnostics without retrieved text. These are diagnostic signals; "
            "answer-span mismatches still require review against verified citations before being "
            "called factual errors."
        )
    lines += [
        "",
        "## Reproduction", "",
        "```powershell",
        ".\\.venv\\Scripts\\python.exe -m scripts.prepare_final_eval",
        ".\\.venv\\Scripts\\python.exe -m scripts.evaluate_final",
        ".\\.venv\\Scripts\\python.exe -m scripts.evaluate_final --check-indexed-coverage",
        ".\\.venv\\Scripts\\python.exe -m scripts.evaluate_final --live --dev-smoke --confirm-api-usage",
        ".\\.venv\\Scripts\\python.exe -m scripts.evaluate_final --live --final --confirm-api-usage",
        "```", "",
        "The live commands require a positive local `INVESTIGATION_DAILY_BUDGET`; `--final` "
        "requires explicit API-usage confirmation and a fresh read-only Frankfurt corpus/evidence "
        "preflight. The first live step should be the one-question dev smoke. Review its request "
        "count and provider quota before approving the final run.", "",
        "## Current preflight evidence", "",
        "- The deterministic dataset builder passed: 45 cases and 62/62 answerable support "
        "references in the local generated corpus. The candidate pool SHA-256 matches the prior "
        "corpus audit; selected candidate answers were copied unchanged.",
        "- The previous read-only production coverage report records 40/40 candidates and 92/92 "
        "support references in the indexed corpus. A new Frankfurt query was attempted but did "
        "not return a result in this workstation session; current live coverage is not independently verified.",
        "- `pytest -q`: 224 passed. The limited development smoke command was blocked before model "
        "loading, database connection, or Gemini requests because the local daily budget is 0.",
        "- No full final evaluation, production write, schema change, deployment, or held-out Gemini call was performed.", "",
    ]
    return "\n".join(lines)

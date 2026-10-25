# Reports

The main findings are in the [Evaluation Report](../EVALUATION_REPORT.md).
This folder contains the measurements and notes behind those results. Each
report describes a particular test or run, so its numbers should be read in
that context rather than treated as live performance statistics. Some earlier
reports mention migrations or deployments that were pending at the time; the
main README and requirements coverage include later updates.

## Key reports

- [Final evaluation](final_evaluation.md) — answer quality, retrieval, and known limitations
- [50K corpus measurements](capacity_50k.md) — database size and indexing checks
- [Search experiments](retrieval_tuning_50k.md) — why Semantic became the default
- [Document processing](document_ingestion.md) — parsing and chunking
- [Uploaded-document retrieval](replacement_semantic_retrieval.md) — a retrieval failure and its fix
- [Quality investigation](phase7_4_quality_improvement.md) — citation rejection and conflict handling
- [Render checks](render_preflight.md) — startup and memory observations
- [Requirements coverage](final_submission_checklist.md) — how each assignment requirement is implemented and verified

## Data files

The JSON files hold recorded measurements, audits, and development diagnostics.
Some evaluation scripts refer to these exact filenames, which is why they have
not been moved.

## Earlier work

Older benchmarks and step-by-step development notes are kept in the
[archive](archive/README.md). They remain available for reference, but the
final evaluation report is the place to look for the submitted results.

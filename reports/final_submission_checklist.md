# UPGAMING Assignment Compliance Checklist

The authoritative source used for this audit is the original eight-page,
text-extractable UPGAMING Applied AI assignment PDF supplied with the task and
read from the local user workspace. The PDF is not copied into this repository.
Statuses distinguish implemented/local-verified behavior from operator-reported
or independently unverified production behavior.

| Requirement | Implementation location | Verification evidence | Status |
| --- | --- | --- | --- |
| Accept at least three file formats and extract text | app/ingestion/parsers.py; tests/test_document_parsers.py | Parser tests cover text PDF, DOCX, TXT, Markdown and reject scanned/image-only PDFs. Three manual fixtures are in tests/fixtures/manual_upload_smoke/. | PASS |
| Extract useful metadata and preserve source identity | app/ingestion/parsers.py; app/ingestion/managed_documents.py; app/db/managed_uploads.py | Tests cover PDF/DOCX metadata, Markdown heading title, filename, format, and content metadata. | PASS |
| Chunk text, handle duplicates, add/update/delete documents | app/ingestion/managed_documents.py; app/db/managed_uploads.py; app/api/documents.py | Unit/API tests cover content-addressed identity, ownership, duplicate rejection, replacement and deletion. Owner later reported live CRUD smoke tests; all-format live behavior was not independently checked in this audit. | PARTIAL |
| Compare at least two chunking strategies | app/ingestion/chunkers.py; scripts/compare_chunking.py | Reproducible synthetic fixture comparison in reports/document_ingestion.md; fixture is not 50K corpus evidence. | PASS |
| Use embeddings and a vector-capable database | app/retrieval/semantic.py; app/db/queries.py; migrations/schema.sql | Real 50K run recorded 384-dimensional BGE embeddings, halfvec storage, pgvector/HNSW and cosine search in reports/capacity_50k.md. Historical database check, not remeasured here. | PASS |
| Implement semantic and keyword search and combine them | app/retrieval/semantic.py; app/retrieval/keyword.py; app/retrieval/engine.py | Recorded Frankfurt evaluation compares Semantic, Keyword and Hybrid on the same 30 answerable cases in EVALUATION_REPORT.md. | PASS |
| Implement an in-project ranking component | app/retrieval/ranker.py | Unit tests cover Weighted RRF configuration, deterministic ranking, duplicate results and edge cases; retrieval evaluations use the implementation. | PASS |
| Combine multiple sources and handle multi-step investigations | app/llm/agent.py; app/llm/tools.py | Owner supplied a live Cyma Watches / Universal Genève answer with two distinct cited chunks; automated final evaluation includes 25 multi-hop cases. Multi-hop errors remain. | PARTIAL |
| Ground factual claims with source citations | app/reasoning/citations.py; app/api/investigations.py | Automated tests and final report: 38/45 draft citations passed retrieved-chunk/exact-quote checks. Quote presence does not prove entailment. | PASS |
| Attempt contradiction detection and report insufficient evidence | app/reasoning/contradictions.py; app/reasoning/abstention.py; app/llm/agent.py | Original 7-fixture result was 1/7. After the development-selected validator fix, a separate post-hoc rerun returned 7/7; synthetic evaluation abstentions were 8/8. This is a small sample and model groups do not prove logical incompatibility. | PARTIAL |
| Handle LLM failures and structured tool calls | app/llm/gemini_client.py; app/llm/tools.py; app/llm/agent.py | Unit tests cover provider errors, timeouts, bounded tool steps and request limits; recorded live runs used structured search calls. | PASS |
| Provide at least 40 evaluation questions spanning required categories | eval/final_answer_eval.jsonl; eval/final_answer_eval_manifest.json | Final set contains 45 cases: 25 multi-hop, 5 single-hop, 8 unanswerable and 7 conflict fixtures. Development set is separate. | PASS |
| Quantitatively evaluate retrieval and answer quality, compare configurations, analyze failures | scripts/evaluate_final.py; EVALUATION_REPORT.md; reports/final_evaluation.md | Retrieval compared across three modes; Semantic answer quality measured on 38 production-path cases; documented failure analysis. Keyword/Hybrid answer-generation comparison was not run. | PARTIAL |
| Provide Python backend and usable document/question/source interface | app/main.py; app/api/; app/templates/; app/static/ | Full local suite includes API, UI markup, error, and security tests. Owner reported live application/CRUD smoke; current Render revision was not independently verified. | PARTIAL |
| Process at least 50,000 records and preserve provenance/reproducibility | scripts/build_corpus.py; scripts/ingest_phase5.py; reports/capacity_50k.md | Recorded run reached exactly 50,000 documents, 50,018 provenance rows, 50,000 chunks; idempotence and evidence coverage passed. Corpus source/revision/seed/hash are documented; generated corpus is Git-ignored. | PASS |
| Use the assignment's dataset attachment or explain an approved alternative | scripts/build_corpus.py; reports/corpus_audit.json; reports/capacity_50k.md | No separate dataset attachment is present in this repository. The assignment lists HotpotQA as an allowed source; the project used a pinned HotpotQA distractor train sample. Confirm with the evaluator whether this resolves “attached dataset” wording or whether another attachment was intended. | PARTIAL |
| Deploy a public demo on free hosting and document persistence/secrets/limits | render.frankfurt.yaml; reports/phase6b_2_activation.md; README.md | Owner supplied the public URL and Frankfurt activation details. No authenticated Render access is available in this packaging audit; current service, deployed commit, Blueprint linkage, cold-start state and persistent DB access were not rechecked. | PARTIAL |
| Maintain quality, tests, technical documentation and cost/resource awareness | app/; tests/; docs/; reports/; README.md | Local pytest is required and run for this milestone; storage, latency, request limits, memory limitations and exact-quote limitations are documented. Render Free behavior under repeated/concurrent investigations is not fully sampled. | PARTIAL |
| Deliver GitHub repository, Live Demo, README, Evaluation Report, AI Usage Report | Repository root; live URL in README.md | Root README, evaluation report and AI usage report are included. GitHub repository and public URL are owner-provided; current public deployment state remains unverified here. | PARTIAL |

## Specific submission risks

1. **Dataset attachment:** the repository has the reproducible 50K HotpotQA
   source named in the assignment, but no separate task-attached dataset file.
   Resolve whether the evaluator expects a different private attachment.
2. **Render Blueprint linkage:** render.frankfurt.yaml is the intended
   Frankfurt config. render.yaml still defines the older service. This audit
   cannot inspect Render Dashboard linkage, so both files remain. Verify the
   Frankfurt service name, region, build/start commands, environment variables,
   and exact deployed commit in Render before submission.
3. **Production verification:** the public URL, migration and live CRUD smoke
   were supplied by the owner. Current live health, all-format uploads,
   deployed code revision, and post-deploy memory under three sequential plus
   two concurrent investigations were not independently measured here.
4. **Answer quality:** overall correctness is 27/38 on a small final set; the
   central-claim answer-span proxy is 19/30. The DHL relationship-binding error
   and quote-versus-entailment limitation should be discussed honestly.

## Keep-alive decision

No scheduled GitHub health workflow or database-touching endpoint was added.
GET /health verifies only that the application process responds; it does not
access Supabase and therefore cannot guarantee that the database avoids
inactivity pausing. Render's free service can sleep and scheduled pings are not
reliable uptime guarantees. For the demo, open the service shortly before use
and allow the cold start. Do not add database credentials to a workflow.

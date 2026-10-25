# Assignment Requirements Coverage

This table maps each assignment requirement to the code that implements it and
the evidence that it works. Limitations are stated next to the requirement they
affect.

| Requirement | Implementation | Evidence |
| --- | --- | --- |
| Accept at least three file formats and extract text | app/ingestion/parsers.py | Parser tests cover text PDF, DOCX, TXT and Markdown, and reject scanned image-only PDFs. Sample files are in tests/fixtures/manual_upload_smoke/. |
| Extract useful metadata and preserve source identity | app/ingestion/parsers.py; app/ingestion/managed_documents.py; app/db/managed_uploads.py | Tests cover PDF/DOCX metadata, Markdown heading titles, filename, format and content metadata. |
| Chunk text, handle duplicates, add/update/delete documents | app/ingestion/managed_documents.py; app/db/managed_uploads.py; app/api/documents.py | Unit and API tests cover content-addressed identity, ownership, duplicate rejection, replacement and deletion. Upload, replace and delete were also smoke-tested on the live demo. |
| Compare at least two chunking strategies | app/ingestion/chunkers.py; scripts/compare_chunking.py | Reproducible fixture comparison in reports/document_ingestion.md (synthetic fixture, not the 50K corpus). |
| Use embeddings and a vector-capable database | app/retrieval/semantic.py; app/db/queries.py; migrations/schema.sql | The 50K ingestion run recorded 384-dimensional BGE embeddings, halfvec storage, pgvector/HNSW and cosine search (reports/capacity_50k.md). |
| Implement semantic and keyword search and combine them | app/retrieval/semantic.py; app/retrieval/keyword.py; app/retrieval/engine.py | Semantic, Keyword and Hybrid are compared on the same 30 answerable cases in EVALUATION_REPORT.md. |
| Implement an in-project ranking component | app/retrieval/ranker.py | Unit tests cover the Weighted RRF configuration, deterministic ranking, duplicates and edge cases. Retrieval evaluations use this implementation. |
| Combine multiple sources and handle multi-step investigations | app/llm/agent.py; app/llm/tools.py | The final evaluation includes 25 multi-hop cases (14 correct). The live demo answers the Cyma Watches / Universal Genève question with two cited chunks (docs/DEMO_WALKTHROUGH.md). Multi-hop relation errors remain; see the DHL case. |
| Ground factual claims with source citations | app/reasoning/citations.py; app/api/investigations.py | 38/45 draft citations passed the retrieved-chunk and exact-quote checks in the final run. Quote presence does not prove entailment. |
| Attempt contradiction detection and report insufficient evidence | app/reasoning/contradictions.py; app/reasoning/abstention.py; app/llm/agent.py | Unanswerable cases: 8/8 abstained. Conflict fixtures: 1/7 in the original run, 7/7 in a separate post-hoc rerun after a fix chosen on development fixtures. The sample is small. |
| Handle LLM failures and structured tool calls | app/llm/gemini_client.py; app/llm/tools.py; app/llm/agent.py | Unit tests cover provider errors, timeouts, bounded tool steps and request limits. Live runs used structured search tool calls. |
| Provide at least 40 evaluation questions spanning required categories | eval/final_answer_eval.jsonl; eval/final_answer_eval_manifest.json | 45 cases: 25 multi-hop, 5 single-hop, 8 unanswerable and 7 conflict fixtures. The development set is separate. |
| Evaluate retrieval and answer quality, compare configurations, analyze failures | scripts/evaluate_final.py; EVALUATION_REPORT.md; reports/final_evaluation.md | Retrieval compared across three modes; Semantic answer quality measured on 38 live-path cases; failure analysis included. Keyword and Hybrid were compared on retrieval only, to stay within the Gemini quota. |
| Provide a Python backend and a usable interface | app/main.py; app/api/; app/templates/ | The test suite covers the API, UI markup, error handling and security. The live demo serves the question page and the document library. |
| Process at least 50,000 records and preserve provenance | scripts/build_corpus.py; scripts/ingest_phase5.py; reports/capacity_50k.md | The recorded run reached 50,000 documents, 50,018 provenance rows and 50,000 chunks; idempotence and evidence coverage checks passed. Source revision, seed and hash are documented. |
| Use the assignment's dataset or an allowed alternative | scripts/build_corpus.py; reports/corpus_audit.json | HotpotQA is listed in the assignment as an allowed source. The project uses a pinned sample of the HotpotQA distractor train split. |
| Deploy a public demo on free hosting; document persistence, secrets and limits | render.frankfurt.yaml; README.md | Live on Render Free (Frankfurt) with a Frankfurt Supabase database. Secrets live only in the Render Dashboard. Limits are documented in the README. |
| Maintain code quality, tests, documentation and cost awareness | app/; tests/; docs/; reports/; README.md | The full test suite runs offline. Storage, latency, request limits and memory measurements are documented. Memory under repeated or concurrent load on Render has not been measured. |
| Deliver repository, live demo, README, evaluation report and AI usage report | Repository root | README.md, EVALUATION_REPORT.md, AI_USAGE_REPORT.md and the live demo URL in the README. |

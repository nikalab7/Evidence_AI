# EvidenceAI project requirements

This file summarizes the project requirements for implementation. The full
assessment prompt and personal planning notes remain local and are excluded from
Git.

- Process at least three file formats; extract text and source metadata; chunk,
  deduplicate, add, update, and delete documents; compare two chunking strategies.
- Use vector embeddings and semantic search, combined with keyword search in a
  hybrid retriever. Implement at least one ranking component in project code.
- Build evidence-grounded multi-document RAG that handles multistep questions,
  citations, conflicts, insufficient evidence, and LLM failures.
- Include at least one structured tool call or equivalent mechanism.
- Provide at least 40 evaluation questions covering simple, multistep,
  unanswerable, and conflicting cases; compare configurations and report
  retrieval and answer-quality metrics with failure analysis.
- Deliver a Python backend and usable interface for document management,
  questions, answers, and source inspection.
- Use a reproducible dataset containing at least 50,000 independent documents
  or text records. Preserve source identity and verify supporting evidence.
- Deploy a public demo on free infrastructure, preserve database data across
  restarts, protect secrets, and document resource and cost limits.
- Maintain modular Python code, error handling, automated tests, technical
  documentation, and an AI usage report.

Exact quote matching establishes that quoted text appears in a source. It does
not by itself show that the source entails the claim.

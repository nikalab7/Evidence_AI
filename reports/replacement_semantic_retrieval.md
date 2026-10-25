# Semantic retrieval after managed-document replacement

Date: 2026-10-25

## Status

The production symptom was reproduced once through the existing public
Frankfurt API: HTTP 200, `status=insufficient`, zero claims, and zero citations.
The database was not changed and no deployment was performed. The code change
below is local and must be manually deployed before it can affect Render.

The design-level weakness is confirmed: semantic retrieval used only Gemini's
focused tool query to embed chunk-body text. Source title aliases were returned
for display and keyword search, but were not used to select semantic candidates.
Consequently, a rewritten query can lose the exact title needed to find a newly
uploaded document. The exact cause of the particular failed Render requests is
not fully established: fresh read-only tests ranked the same document first,
and the public response does not include an internal stage trace. Do not claim
that the historical failure was definitively caused by HNSW or Gemini rewriting.

## Read-only diagnosis

All database checks below used the fail-closed Frankfurt project guard and a
read-only transaction. The exact synthetic managed record was found with its
updated filename and stable stored title. Its current text contains the new
fact, not the replaced fact, and it has three chunks. No content, credentials,
or record IDs were printed. Mindo and Sydney were not accessed.

| Check | Observed result |
| --- | --- |
| Exact user question, BGE query embedding, existing semantic SQL | Target document ranked 1 in top 5 |
| Same question with `source_split=managed_upload` | Target ranked 1 in top 10 |
| Existing keyword SQL, exact user question | Target ranked 3 in top 10 |
| Actual one-call Gemini tool-planning probe | Generated one `search_evidence` call; query differed from the user question but retained the exact title, `silver`/`keys`, and `cobalt`/`lighthouse` terms |
| That generated query, existing semantic SQL | Target ranked 1 in top 5 and top 100 |
| That generated query, keyword SQL | Target ranked 2 in top 10 |
| HNSW vs. index-scan-disabled semantic query | Target rank remained 1; `EXPLAIN ANALYZE` used `chunks_embedding_hnsw_idx` |
| Existing public Frankfurt `POST /api/investigate` | HTTP 200, `insufficient`, zero claims/citations, no trace fields |

The direct database results rule out a repeatable title-loss, filter, or HNSW
miss for the exact query and the captured Gemini rewrite. They do not reveal
what tool query or retrieved evidence accompanied the earlier failed Render
requests. The deployed endpoint currently strips internal traces, and no
authenticated Render log access was available to inspect the old request.

One local full investigation on the same synthetic question answered with one
verified citation. It used three Gemini HTTP requests, retrieved five chunks,
and took 3.604 seconds total; the Gemini calls totaled 2.533 seconds. This run
occurred before the final optimization that skips the title rescue when the
normal semantic results already contain the exact alias. No second full Gemini
run was made after that small optimization to avoid unnecessary API use.

## Change made

1. Semantic retrieval now extracts only high-confidence exact references from
   identifiers, quoted titles, and title-case phrases, using the same Unicode
   normalization as ingestion. It considers the original question as well as
   Gemini's rewritten tool query.
2. If the normal semantic candidates do not contain an exact matching title
   alias, a parameterized SQL query scopes cosine ranking to exact alias
   matches. It accepts at most three aliases, refuses aliases matching more
   than 25 documents, materializes matching chunks before vector sorting, and
   returns at most three rescue chunks. This avoids relying on the global HNSW
   shortlist for a narrow newly uploaded document.
3. If normal semantic results already contain the exact title alias, their
   order is unchanged and no extra SQL query runs. Keyword and hybrid modes,
   global result limits, RRF weights, schema, and citation rules remain intact.
4. Gemini is instructed to preserve exact titles, identifiers, distinctive
   names, and quantities when forming search queries.
5. Safe internal traces and server logs distinguish `evidence_not_retrieved`,
   `evidence_retrieved_but_not_cited`, `citation_rejected`, `model_abstained`,
   `central_claim_unverified`, `final_response_unavailable`, `invalid_final_response`,
   `generation_failed`, and `citations_verified`. They contain status
   codes, counts, timings, and a query-equality boolean only. They exclude
   question text, document titles/text, chunk IDs, and exact quotes. Public API
   responses continue to omit all internal traces.

Exact quote validation still proves quote presence only; it does not prove that
the quote entails the claim.

## Development retrieval comparison

The comparison used only the fixed `eval/retrieval_dev.jsonl` set of 200
questions, candidate K=20, BGE-small-en-v1.5, and supporting-title Recall@K/MRR.
The prior Phase 6A run recorded all 200 as eligible. A fresh broad evidence
coverage query timed out at 30 seconds and was canceled; the corpus was not
changed, so the comparison used that same previously verified eligible set.
The 40 held-out candidates were not opened.

| Semantic configuration | Recall@5 | Recall@10 | MRR |
| --- | ---: | ---: | ---: |
| Existing semantic ranking | 0.8425 | 0.8775 | 0.928266 |
| Exact-title rescue, final bounded trigger | 0.8700 | 0.9050 | 0.936599 |

169 questions contained a high-confidence title reference. In 67, that title
was absent from the normal top-20 and triggered the fallback. The fallback
added 14 unique chunks across the 200 questions. Recall@5 and Recall@10 each
rose by 0.0275; MRR rose by 0.008333. MRR decreased for two individual
questions even though its aggregate increased. These are development retrieval
metrics, not answer correctness or entailment measures.

The new behavior added title-scoped SQL only when the named alias was absent
from normal candidates. A separate test confirms questions with no exact title
reference and questions whose exact title is already ranked keep their original
semantic results.

## What remains uncertain

- The public Render request still reproduces the symptom on the version that
  was deployed during this check. The local correction has not been deployed.
- The old request cannot be classified as retrieval miss, Gemini abstention,
  missing citation, or rejected citation because the deployed version did not
  log a sanitized diagnostic outcome. The new log event will distinguish these
  after a manual deployment and retry.
- The title rescue is deliberately conservative: it will not rescue aliases
  matching more than 25 content-addressed documents. Ambiguous title collisions
  therefore continue through ordinary semantic ranking.
- The public endpoint result remains an operational blocker until the corrected
  commit is deployed and the exact question returns a verified citation.

## Verification commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -q tests/test_retrieval.py tests/test_managed_uploads.py tests/test_agent.py tests/test_tools.py tests/test_web_application.py
git diff --check
```

Full suite: **206 passed**. `git diff --check` passed. The public Render request is still insufficient until the corrected
commit is manually deployed; no deployment was done here.

## Manual Render deployment and check

Deploy the final pushed commit to the existing `evidence-ai-frankfurt` service
with its auto-deploy setting unchanged. The checked-in Blueprint commands are:

```text
Build: pip install -r requirements.txt && python scripts/download_model.py
Start: uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-proxy-headers
```

After deployment, verify `/health`, then send one semantic request for the exact
synthetic question. In Render Logs, find the `investigation_diagnostic` JSON
event. It should show `evidence_outcome=citations_verified` and a verified claim
count if the live investigation succeeds. If it is insufficient, use
`evidence_outcome` and the per-tool fallback counters to distinguish retrieval,
abstention, and citation rejection. The log intentionally does not contain the
question or document text. The HTTP response must contain a verified exact quote;
the `citations_verified` code records quote presence, not factual entailment.

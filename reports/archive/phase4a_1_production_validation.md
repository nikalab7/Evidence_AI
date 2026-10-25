# Phase 4A.1 — Production validation and hardening

**Status: local fixes and automated tests are verified. The owner has since
shared a successful live multi-hop response; its Render memory log and broader
production gates remain pending.** No live investigation was sent by the agent
during this work. No Gemini budget was consumed by the agent, and no database
was queried or changed.

## Production evidence supplied by the owner

The following values were supplied in the task context. They were not verified
against authenticated Render logs in this work session:

| Measurement | Owner-supplied value |
| --- | ---: |
| Public service | `https://evidence-ai-frankfurt.onrender.com/` |
| Frankfurt project reference | `nldnpqhqrfwjgxcqeuru` |
| Completed investigation | 1; Sadat X question answered with Anwar Sadat and an exact quote |
| Investigation elapsed time | 2.9497 s |
| Sampled peak RSS | 309,981,184 bytes (295.6 MiB) |
| Reported RSS growth | 5,660,672 bytes (5.4 MiB) |
| Configured process-local investigation budget | 10 per rolling 24 hours |

The owner later shared a successful answer to “The company that oversees Cyma
Watches was founded when?” It combines the Cyma Watches and Universal Genève
source passages and returns two distinct chunk IDs. See
[`docs/INTERVIEW_DEMO.md`](../../docs/INTERVIEW_DEMO.md) for the exact answer and
quotes. This is owner-provided live output, not an independently repeated
request or verified Render log.

The memory sample is below Render Free's 536,870,912-byte limit, but one
owner-reported request does not establish memory behavior across three
sequential requests or two concurrent requests. The deployed environment's
remaining budget and Gemini project's available quota were not independently
checked. The process-local budget also resets on process restart and is not a
global durable quota.

## Fixes prepared

- **Conflict response:** `conflict_groups` now has a top-level field in the
  typed `InvestigationResult`. Previously, the agent put groups inside its
  private trace while the HTTP serializer looked for a top-level field, so the
  public API/UI could lose detected conflicts. Before serialization, groups
  are restricted to IDs of claims that passed citation validation.
- **Repeated claim text:** the result page keeps the answer once, labels each
  claim's citation card, and still displays its exact quotes, titles, and
  source links. Claims absent from the answer text remain visible in full.
- **Rate-limit identity:** the API accepts exactly one valid
  `CF-Connecting-IP` value and ignores `X-Forwarded-For`. If the edge value is
  missing or malformed, it uses the immediate socket peer, which may group
  requests behind the proxy. The Frankfurt Uvicorn command disables automatic
  proxy-header rewriting so a caller-controlled forwarding chain cannot choose
  the limiter key.

Render documents that requests to Render web services pass through
Cloudflare; Cloudflare documents `CF-Connecting-IP` as the client address sent
to the origin. This policy depends on that ingress path remaining in place. If
the service is later exposed through another proxy or a direct origin, verify
which trusted component sets the client IP before changing the policy:
[Render uptime guidance](https://render.com/docs/uptime-best-practices),
[Cloudflare request headers](https://developers.cloudflare.com/fundamentals/reference/http-headers/),
[Render FastAPI proxy guidance](https://render.com/articles/fastapi-production-best-practices).

## Local verification

Focused tests after the conflict-result fix:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_web_application.py tests/test_agent.py tests/test_citations.py
```

Result: **27 passed**. The suite includes conflict serialization and filtering,
private trace suppression, citation preservation, forged `X-Forwarded-For`
rate-limit bypass, valid/missing/duplicate/malformed Cloudflare-header
handling, and the Frankfurt Uvicorn proxy setting. The Blueprint YAML parsed
successfully and the installed Uvicorn CLI supports `--no-proxy-headers`. A
full-suite result is recorded below.

The complete suite then passed: **151 passed** with `python -m pytest -q`.
These are local tests with fake provider/database boundaries. They do not
verify the deployed Render configuration, live Gemini behavior, live database
access, cold start, or production RSS.

## Live checks still pending

This workspace has no authenticated Render deployment/log access. No deploy
was triggered here and the owner-shared response does not identify the exact
deployed commit or verify the current start command. Before further live
checks, confirm that the existing Frankfurt service runs the intended commit
and that the app-level budget remains positive. Avoid a Blueprint environment
sync that would replace the dashboard's current budget with the repository's
fail-closed value. Preserve the Sydney fallback and do not touch Mindo.

After deployment, use the dashboard to confirm the actual service region,
`DATABASE_URL` project reference, model-cache build command, start command, and
the positive `INVESTIGATION_DAILY_BUDGET`. The start command should include
`--no-proxy-headers` and must not include a wildcard
`--forwarded-allow-ips` setting. Do not reveal secret values in screenshots or
logs.

The following sequence uses only development questions from
`eval/retrieval_dev.jsonl`; it does not open or use the held-out candidate file.
Run it only when the owner confirms enough remaining app and Gemini quota.
Each investigation can make up to five Gemini HTTP requests. The three
sequential checks should be more than 60 seconds apart for the same client IP;
wait another 60 seconds before the concurrency pair so the per-IP window is
clear. Stop on any 429 or unexpected service error; do not retry repeatedly.

1. Call `GET /health` and `GET /`; record HTTP status and cold-start elapsed
   time. The cold-start note cannot appear until the server returns the initial
   HTML page.
2. Sequential request 1: `Rapper Sadat X is named for the third President of
   Egypt, who was?` Check for an answered result and verified quote.
3. Sequential request 2: `The company that oversees Cyma Watches was founded
   when?` This development-set question requires evidence associated with both
   `Cyma Watches` and `Universal Genève`; verify the returned citations rather
   than assuming the expected answer.
4. Sequential request 3: `What was the serial number of the fictional
   EvidenceAI test submarine in 1842?` Check that the result abstains instead
   of inventing a value.
5. After the per-IP window clears, submit two distinct development questions
   concurrently to exercise the configured two-request concurrency limit.
6. From Render logs, record the sanitized startup RSS and each
   `investigation_memory` event's before/after/peak RSS, elapsed time,
   concurrency, and outcome. Compare all observed peaks with 536,870,912 bytes.
   Do not include question text, client IPs, keys, or database URLs in the
   report.

Example PowerShell checks (substitute the verified public service URL only).
The POST command below is an example for the owner to run after checking the
remaining app/Gemini quota; it was not executed here. If running the five-call
sequence below, skip this example POST so it does not use an extra slot:

```powershell
$base = 'https://evidence-ai-frankfurt.onrender.com'
Invoke-WebRequest -Uri "$base/health" -Method Get
Invoke-WebRequest -Uri "$base/" -Method Get

$payload = @{ question = 'The company that oversees Cyma Watches was founded when?'; retrieval_mode = 'semantic' } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "$base/api/investigate" -Method Post -ContentType 'application/json' -Body $payload
```

For the concurrency pair, start two PowerShell jobs with two distinct
development-set questions, then `Wait-Job` and `Receive-Job`; first ensure the
per-IP window is clear and that at least two app-level slots remain. The local
fixture tests cover conflict rendering/serialization. Do not add synthetic
conflicting documents to the production corpus for this milestone.

Full owner-run sequence, if the budget has at least five investigation slots
available:

```powershell
$base = 'https://evidence-ai-frankfurt.onrender.com'
function Invoke-EvidenceInvestigation([string]$Question) {
  $body = @{ question = $Question; retrieval_mode = 'semantic' } | ConvertTo-Json -Compress
  Invoke-RestMethod -Uri "$base/api/investigate" -Method Post -ContentType 'application/json' -Body $body
}

$sequentialQuestions = @(
  'Rapper Sadat X is named for the third President of Egypt, who was?',
  'The company that oversees Cyma Watches was founded when?',
  'What was the serial number of the fictional EvidenceAI test submarine in 1842?'
)
foreach ($question in $sequentialQuestions) {
  Invoke-EvidenceInvestigation $question
  Start-Sleep -Seconds 61
}

$parallelQuestions = @(
  'Rapper Sadat X is named for the third President of Egypt, who was?',
  "What is Eminem's seventh album release in June 18, 2010?"
)
$jobs = foreach ($question in $parallelQuestions) {
  Start-Job -ArgumentList $base, $question -ScriptBlock {
    param($url, $question)
    $body = @{ question = $question; retrieval_mode = 'semantic' } | ConvertTo-Json -Compress
    Invoke-RestMethod -Uri "$url/api/investigate" -Method Post -ContentType 'application/json' -Body $body
  }
}
$jobs | Wait-Job | Receive-Job
$jobs | Remove-Job
```

This is intentionally a five-investigation maximum; if the actual remaining
budget is unknown, do not run the sequence. `INVESTIGATION_DAILY_BUDGET` is
process-local and the API does not expose the current remaining count. Do not
restart the service to reset the counter. The owner must verify enough current
capacity before starting, or defer the live checks.

## Gate status

| Gate | Status |
| --- | --- |
| Conflict groups appear in public typed response | Local regression test passed; deployment pending |
| No duplicate answer/claim presentation; citations retained | Local markup regression checks passed; browser/live check pending |
| Forged XFF cannot rotate per-IP limiter key | Local regression test passed; deployment pending |
| Three-request and concurrent-request RSS | Pending owner-run Render log check |
| Public `/health`, page, cited answer, abstention | Pending deployment and owner-run live checks |
| Cold-start after idle | Pending; initial HTML wait cannot itself display the notice |
| Gemini quota and remaining daily budget | Not independently verified |

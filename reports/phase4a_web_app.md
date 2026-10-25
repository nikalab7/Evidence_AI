# Phase 4A — Functional investigation web application

**Status: local implementation and automated HTTP verification passed. Public
Render deployment and live quota/memory gates are pending.** No live Gemini
request or Supabase query was made in this milestone.

## Implemented

- `GET /` serves the same-service responsive question and evidence interface.
- `POST /api/investigate` calls the existing bounded Gemini agent, retrieval
  engine, and citation validator. Semantic retrieval is the default; keyword
  and hybrid are explicit alternatives.
- Public responses contain the answer status, verified claim text, retrieved
  `chunk_id`, exact supporting quote, title aliases, and safe HTTP(S) source
  links. Internal traces and generation errors are not sent to the browser.
- The UI has loading, sanitized error, insufficient-evidence, conflicting-
  evidence, citation, and quote states. It displays 50,000 indexed records and
  the requested free-hosting cold-start notice.
- Requests reject invalid question types/length/control characters, unknown
  fields/modes, and JSON bodies over 16 KiB. Gemini calls have a per-request
  timeout, a total investigation deadline, and at most 1,024 output tokens per
  HTTP request by default. The existing agent still has at most four tool steps
  and five Gemini HTTP attempts.
- One FastEmbed model and one Gemini HTTP client are initialized in the
  application lifespan and reused. A request opens one fail-closed Frankfurt
  database connection and reuses it across its tool calls. Tool transactions
  close before Gemini requests; the connection closes at the end of the
  investigation.
- Startup logs contain sanitized current/high-water RSS. During each
  investigation, a 50 ms sampler records before/after RSS, sampled peak RSS,
  concurrency, elapsed time, and whether the sampled peak is below
  536,870,912 bytes (512 MiB). No question, IP address, credential, or raw
  exception detail is included in these measurements.

## Local verification

The local `.env` configuration check returned project reference
`nldnpqhqrfwjgxcqeuru`, model `gemini-3.5-flash-lite`, and daily budget `0`.
This confirms the configured URL's project identity only; it is not a database
connection check. The zero budget intentionally prevents local or public
investigations until the quota is checked and a limit is configured.

The route-level tests sent HTTP requests through FastAPI using scripted Gemini
responses and a fake database connection. They verified:

- HTTP 200 with an exact-quote citation and title/source URL.
- HTTP 200 with an insufficient-evidence abstention when retrieval is empty.
- Semantic mode is passed when omitted; keyword/hybrid remain selectable.
- Gemini is called only after the database tool transaction has closed.
- 422 validation, 413 oversized body (including streamed input), 429 exhausted
  daily budget, sanitized 502 upstream failure, and 504 timeout responses.
- UI response fields use DOM `textContent`; unsafe source URL schemes are not
  returned as links.
- Atomic quota reservation and two overlapping memory samples.

A local Uvicorn process using the cached model also returned `GET /` HTTP 200
with the 50,000-record label and cold-start notice, and `GET /health` HTTP 200.
`POST /api/investigate` returned the expected HTTP 503 because the actual
process budget is zero; this prevented any Gemini or database call. That local
Windows process logged startup RSS **228,892,672 bytes** and high-water RSS
**263,135,232 bytes** after cached model initialization (application startup
**0.3915 seconds**). These are workstation measurements, not Render results,
and no real investigation memory sample was produced. Visual inspection in the
in-app browser was unavailable in this session; page response and interface
states are covered by route/markup tests.

Commands:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_web_application.py tests/test_public_safeguards.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The full suite result for this change is **147 passed**. Route tests simulate the
Gemini and database boundaries; they do not establish live provider or public
deployment behavior.

## Quota protection and limit

The process-local limiter implements a rolling per-IP limit, an atomic
application-process rolling-24-hour reservation counter, and a concurrent request cap.
The daily unit is reserved before work begins and is not refunded on failure,
because a provider request may already have consumed quota. A single
investigation may issue up to five Gemini HTTP attempts. The rolling 24-hour
window is conservative against Gemini's midnight-Pacific RPD reset, avoiding
an extra allowance at a separate UTC calendar boundary; Google's [rate-limit
guide](https://ai.google.dev/gemini-api/docs/rate-limits) documents that RPD
resets at midnight Pacific time.

`INVESTIGATION_DAILY_BUDGET=0` is the committed fail-closed default. No
arbitrary positive cap was selected: Gemini quota is specific to the API
project/model and is visible in its AI Studio Rate Limits dashboard, as
described in the [official Gemini rate-limit guide](https://ai.google.dev/gemini-api/docs/rate-limits).
This workspace has no quota-dashboard/IAM access, so the actual RPD/RPM/TPM and
remaining quota are **not verified**. Before enabling requests, the owner must
check the `gemini-3.5-flash-lite` project quota and other usage, then set a
conservative investigation count no greater than the remaining daily request
quota divided by five (with headroom for other callers and retries). If the
project's dashboard panels are unavailable, the [official troubleshooting
guide](https://ai.google.dev/gemini-api/docs/troubleshoot-ai-studio) describes
the Google Cloud quota/monitoring permissions needed to view them.

This counter is in RAM. It resets on restart/spin-down and is not shared across
workers or instances; it is only a temporary safeguard, not a restart-proof
global cap. No Redis service or table/schema was created. If a durable global
cap is required, the smallest in-architecture option is an approved atomic
daily counter in the existing PostgreSQL project; that requires a separate
schema approval. A shared managed store is another option but would add
infrastructure.

## Render deployment and memory gate

`render.frankfurt.yaml` statically specifies a distinct Frankfurt service name,
build-time model download/offline verification, offline runtime cache loading, and
`/health`. It sets the daily budget to `0` and declares `DATABASE_URL` and
`GEMINI_API_KEY` as secrets. The local configuration parses the Frankfurt
region and the local `.env` project reference, but this workspace has no Render service URL, service ID,
Render API credential, or deployment/log access. Therefore no Render build,
deploy, public URL request, post-idle test, or live memory measurement was
performed, and the service region/configuration currently in the Render
dashboard is **not verified**. The build script and runtime loader point at the
same project-local `.model_cache`; the local runtime startup successfully loaded
that cache offline. This does not prove the deployed artifact contains it.

No actual post-startup or investigation RSS numbers are available for this
change. The prior FastEmbed startup measurement is a historical baseline only;
it does not include Gemini requests, database activity, or concurrent
investigations. The new logs are instrumentation, not evidence that the live
service fits under the [Render Free 512 MB limit](https://render.com/docs/compute-plans).
The [Render Free service guide](https://render.com/docs/free) explains the
idle spin-down and cold-start behavior. The page's note cannot show until the
server sends the initial HTML response.

### Required operator actions

1. In Google AI Studio, open the project associated with the configured Gemini
   key and check its current `gemini-3.5-flash-lite` request limits and usage.
   Choose a daily investigation budget with enough remaining quota for the
   intended smoke/memory run (five test investigations can each use up to five
   HTTP attempts); include headroom for retry/provider usage.
2. In the Frankfurt Render service, confirm the actual region and build/start
   settings match `render.frankfurt.yaml`. Set its backend-only `DATABASE_URL`
   and `GEMINI_API_KEY` secrets, then set the quota-reviewed positive
   `INVESTIGATION_DAILY_BUDGET`. Deploy the intended commit manually because
   auto-deploy is disabled. Do not change or delete the Sydney fallback.
3. After deploy, verify the offline model build log, startup embedding check,
   startup RSS log, `/health` HTTP 200, and `GET /` page. After at least 15
   minutes idle, open the public URL and record the cold-start time; the note
   will appear only after HTML arrives.
4. Make three real investigations, waiting at least 60 seconds between requests
   from the same IP to respect the two-per-minute limit. Then run two real
   investigations concurrently. Record each `investigation_memory` event,
   startup RSS, sampled peak, and observed growth; compare with 512 MiB. Also
   verify one cited answer and one insufficient-evidence response through the
   public HTTP endpoint. These requests may consume up to 25 Gemini HTTP
   attempts in total.

Until these steps are recorded, deployment and Render memory acceptance remain
pending; the local implementation must not be described as a publicly working
demo.

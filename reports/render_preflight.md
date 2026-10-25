# Render FastEmbed Preflight

Date: 2026-10-24

This is an early startup and model-loading measurement from before the
investigation interface and document management were added. It is a useful
baseline, **not** a measurement of the complete application under live
investigation or upload load.

## Scope

This check loads `BAAI/bge-small-en-v1.5`, embeds one query, verifies its
dimensions, and records startup timing and process memory. No dataset was
ingested. The result covers the minimal API and embedding model, not the RAG
pipeline.

## Actual Render startup result

Source: Render startup log.

| Measurement | Result |
| --- | ---: |
| Status | passed |
| Runtime | Linux x86_64, Python 3.11.9 |
| Render CPU allocation | 0.15 |
| Model | `BAAI/bge-small-en-v1.5` |
| Output dimensions | 384 |
| Model initialization | 7.2839 s |
| First query embedding | 0.1003 s |
| Smoke duration | 7.3842 s |
| App startup through embedding check | 12.6925 s |
| RSS before model | 105,291,776 B (100.4 MiB) |
| RSS after model | 299,245,568 B (285.4 MiB) |
| RSS after embedding / peak RSS | 300,912,640 B (287.0 MiB) |
| RSS increase over baseline | 195,620,864 B (186.5 MiB) |

The peak is below Render Free's documented 512 MB memory limit. The recorded
value is this process's RSS/peak RSS; it is not a measurement of every process
or service-level metric in the Render dashboard.

The recorded Render memory gate is **verified** from this owner-supplied log:
384 dimensions, 100.3 ms first query embedding, and 287.0 MiB peak RSS. The
machine-readable measurements are in `reports/render_preflight.json`; the
readiness gate reads that file and returns to `not_verified` if the evidence is
missing, invalid, or over 512 MiB. A separate restart check is still pending.

## Build-time model cache

The 7.2839-second Render model initialization is a baseline measurement. It does
not say whether the process downloaded the model, so the cause is not inferred.
The Render build command runs `scripts/download_model.py`, which downloads to the
same absolute project-local `.model_cache/` path used at runtime. It verifies a
384-dimensional embedding, then reloads the model with `local_files_only=True`
and verifies a second 384-dimensional embedding. Runtime also uses
`local_files_only=True`, so it cannot download a missing model during startup.

This repository change has not yet been deployed to Render, so the deployed
build artifact and post-change startup log are not verified here. After a manual
deployment, confirm the `fastembed_build_cache` event reports
`offline_load_passed: true`, then compare the startup event's dimensions, model
initialization time, query latency, and memory with this baseline. Timing is a
measurement and does not identify whether a download occurred.

The earlier local build command completed successfully on Windows: it cached 9
files (67,181,330 bytes), verified a 384-dimensional query embedding, and passed
the then-current manifest check. Two independent local application processes
each returned HTTP 200 from `/health`; one startup log reported a verified 9-file
cache and 0.8944-second model initialization. Those checks predate the
offline-only loader. After that change, the current `scripts/download_model.py`
completed locally and reported `offline_load_passed: true` with 384 dimensions.
A local FastAPI lifespan startup with the embedding startup check enabled
completed, and `GET /health` returned HTTP 200. The current full pytest suite
passed 43 tests. These local checks do not verify that Render's next built
artifact contains the cache; that requires a deployment.

## Restart check

This log confirms one successful Render startup and embedding check. It does not
show a separate restart followed by another successful `/health` response and
startup event. That restart check remains pending.

## Local baseline

Environment: Windows 10, Python 3.11.9, FastEmbed 0.9.0. Dependencies were
installed in a temporary directory after the existing virtual environment hit
a Windows file lock.

The first real-model run downloaded the model and passed the dimension check:

| Measurement | Result |
| --- | ---: |
| Output dimensions | 384 |
| Model initialization including first download | 21.8160 s |
| First query embedding | 0.0205 s |
| Smoke duration | 21.8365 s |

That first run exposed a Windows RSS-reader issue, so memory was not available
until the reader was corrected. After the correction, two separate warm-cache
Uvicorn processes returned `{"status":"ok"}` from `/health`:

| Process | App startup | Model initialization | Query embedding | RSS after embedding | Peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.9177 s | 0.2719 s | 0.0148 s | 223,174,656 B (212.9 MiB) | 257,269,760 B (245.3 MiB) |
| 2 | 0.8501 s | 0.2485 s | 0.0133 s | 223,420,416 B (213.1 MiB) | 257,769,472 B (245.8 MiB) |

These launches verify local process restart behavior. They do not substitute for
the pending Render restart check.

## Safety checks

- At this early preflight checkpoint, `/health` was the only registered route.
  The later app also serves investigation and document-management routes.
- `/docs` and `/openapi.json` returned 404 in automated tests.
- Vectors and credentials are absent from HTTP responses and startup logs.
- `render.yaml` contains no service credentials and disables automatic deploys.
- The startup log contains status and aggregate measurements only.

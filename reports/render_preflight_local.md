# Render FastEmbed Preflight: Local Baseline

Date: 2026-10-24

## Scope

This is a local Windows baseline for the Render startup probe. It does not
verify Render's Linux runtime, memory limit, cold boot, or remote restart. No
dataset was ingested.

## Setup

- Python 3.11.9
- FastEmbed 0.9.0
- Model: `BAAI/bge-small-en-v1.5`
- One query per smoke check; one inference thread
- Model dependencies were installed in a temporary isolated directory after
  Windows returned a file-lock error while pip was updating the project venv.

## Results

The first real-model run fetched the model and passed the dimension check:

| Measurement | Result |
| --- | ---: |
| Output dimensions | 384 |
| Model initialization, including first model download | 21.8160 s |
| First query embedding | 0.0205 s |
| Smoke duration | 21.8365 s |

That first run exposed a Windows RSS-reader issue, so it did not return memory
values. The reader was fixed and measured again in two separate Uvicorn
processes. Both returned `{"status":"ok"}` from `/health` after startup.

| Uvicorn process | App startup | Model initialization | Query embedding | RSS after embedding | Peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.9177 s | 0.2719 s | 0.0148 s | 223,174,656 B (212.9 MiB) | 257,269,760 B (245.3 MiB) |
| 2 | 0.8501 s | 0.2485 s | 0.0133 s | 223,420,416 B (213.1 MiB) | 257,769,472 B (245.8 MiB) |

These two process launches confirm the local startup path and local restart
behavior with the model cache already warm. They do not establish Render
behavior. The first cold download timing was measured outside Uvicorn; its RSS
was unavailable because of the issue described above.

## Safety and API checks

- Only `/health` is registered.
- `/docs` and `/openapi.json` returned 404 in automated tests.
- Model vectors and credentials are not included in HTTP responses or startup
  logs. The log includes only model name, dimensions, timings, process memory,
  Python/platform details, and status.
- `render.yaml` contains no service credentials.

## Status and next step

Local code and restart checks passed. Render deployment, Linux RSS/peak RSS,
Render startup time, and an actual Render restart remain unverified until this
Blueprint is deployed and its service logs are checked. Keep bulk ingestion
blocked until those measurements pass. Then begin the separate HotpotQA
uniqueness and evaluation-evidence coverage audit.

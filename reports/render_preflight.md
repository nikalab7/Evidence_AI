# Render FastEmbed Preflight

Date: 2026-10-24

## Scope

This check loads `BAAI/bge-small-en-v1.5`, embeds one query, verifies its
dimensions, and records startup timing and process memory. No dataset was
ingested. The result covers the minimal API and embedding model, not the RAG
pipeline.

## Actual Render startup result

Source: startup log supplied by the project owner.

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
| RSS after embedding / peak RSS | 300,912,640 B (286.9 MiB) |
| RSS increase over baseline | 195,620,864 B (186.5 MiB) |

The peak is below Render Free's documented 512 MB memory limit. The recorded
value is this process's RSS/peak RSS; it is not a measurement of every process
or service-level metric in the Render dashboard.

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

- `/health` is the only registered route.
- `/docs` and `/openapi.json` returned 404 in automated tests.
- Vectors and credentials are absent from HTTP responses and startup logs.
- `render.yaml` contains no service credentials and disables automatic deploys.
- The startup log contains status and aggregate measurements only.

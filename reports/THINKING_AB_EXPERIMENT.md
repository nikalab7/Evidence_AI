# Gemini Thinking A/B Experiment

**Goal:** Compare Gemini 3.5 Flash-Lite at its original/default minimal thinking level against medium thinking, with all other pipeline settings fixed. No production configuration changes are made on this branch unless you explicitly deploy it.

## Configuration

`GEMINI_THINKING_LEVEL` accepts blank (provider default), `minimal`, `low`, `medium`, `high`. Supported by Gemini 3.5 Flash-Lite; model-specific support varies. Blank preserves previous request JSON. Both tool-calling and final structured-output requests use the same level.

The original defaults remain unchanged: `GEMINI_MAX_OUTPUT_TOKENS=1024`, `GEMINI_REQUEST_TIMEOUT_SECONDS=15`, `INVESTIGATION_TIMEOUT_SECONDS=90`. For fair comparison, configure **both arms identically** except for `GEMINI_THINKING_LEVEL`, with a higher output cap to avoid truncating thinking tokens.

Recommended test overrides for **both** arms:
```sh
export GEMINI_MODEL=gemini-3.5-flash-lite
export GEMINI_MAX_OUTPUT_TOKENS=4096
export GEMINI_REQUEST_TIMEOUT_SECONDS=45
export INVESTIGATION_TIMEOUT_SECONDS=180
export INVESTIGATION_DAILY_BUDGET=10
# Keep DATABASE_URL, GEMINI_API_KEY, and INVESTIGATION_DAILY_BUDGET on the approved private environment.
python -m pytest -q tests/test_gemini_client.py tests/test_compare_thinking_runs.py
```

## Paid, read-only experiment (requires local credentials, corpus, indexed DB, and explicit API-use confirmation)

Preflight `python -m scripts.evaluate_final` (offline, no Gemini request). The live final path also requires the locally regenerated 50K corpus/gold-evidence audit. Budget: **set INVESTIGATION_DAILY_BUDGET=10 for each arm**; 10 multi-hop cases per arm = 20 investigations, up to 100 Gemini HTTP attempts total; provider charges/quota may apply. The arms intentionally use separate ledgers because evaluation run keys do not include thinking level. Their independent limits sum to 20, so do not rerun with a fresh ledger without tracking total cost.

**Arm A — baseline:**

```sh
export GEMINI_THINKING_LEVEL=minimal
python -m scripts.evaluate_final --live --final --confirm-api-usage --max-investigations 10 \
  --results reports/.thinking_minimal_results.jsonl \
  --ledger reports/.thinking_minimal_budget.jsonl \
  --report reports/.thinking_minimal_report.md \
  --retrieval-results reports/.thinking_retrieval.json
```

**Arm B — medium:**

```sh
export GEMINI_THINKING_LEVEL=medium
python -m scripts.evaluate_final --live --final --confirm-api-usage --max-investigations 10 \
  --results reports/.thinking_medium_results.jsonl \
  --ledger reports/.thinking_medium_budget.jsonl \
  --report reports/.thinking_medium_report.md \
  --retrieval-results reports/.thinking_retrieval.json
```

The first ten final cases are multi-hop. Use separate result **and ledger** paths for the two settings; the existing evaluation run key includes model and case, **not thinking level**. These 10-case runs are preliminary diagnostic samples; expand to all 25 multi-hop examples before drawing stronger conclusions. Do not overwrite historical reports.

## Compare measured results

```sh
python -m scripts.compare_thinking_runs \
  reports/.thinking_minimal_results.jsonl reports/.thinking_medium_results.jsonl
```

Review paired answer correctness and case-by-case changes (especially the DHL relationship case), rejected citations, failed requests, total tool calls, API call counts, and latency. Report actual denominators rather than assuming all 10 cases completed. A different outcome is not necessarily caused by Thinking alone: sampling, quotas, timeouts and truncation may affect each attempt. Repeated runs are preferable for a confident conclusion.

Relevant API docs: https://ai.google.dev/gemini-api/docs/generate-content/thinking

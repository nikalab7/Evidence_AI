# AI Usage Report

## Tools

- **OpenAI Codex** and **Anthropic Claude** were used as coding and review
  assistants.
- **Google Gemini (gemini-3.5-flash-lite)** is part of the product: it runs the
  investigation agent. It was not used to write code.

## How AI assistance was used

AI assistants helped with implementation, tests, documentation drafts, and UI
iterations. I defined the architecture, scope, and evaluation design, and made
the trade-off decisions: Supabase with pgvector, the Frankfurt migration,
Semantic as the default retrieval mode, isolation of the held-out evaluation
set, and the security boundaries for document management.

## Verification

I reviewed the generated code and ran the automated test suite and the live
checks. Results are reported only where a recorded measurement exists; see
[EVALUATION_REPORT.md](EVALUATION_REPORT.md). The held-out evaluation cases
were not used for tuning.

## Responsibility

I am responsible for the submitted code and can explain and modify any part of
it.

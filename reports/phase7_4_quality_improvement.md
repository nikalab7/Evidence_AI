# Phase 7.4 - Targeted quality improvement

Status: development comparison and verification complete. The original 45-case
metrics and result checkpoint remain frozen at the Phase 7.3 baseline. A later,
separately approved seven-conflict post-hoc check is recorded in
[final_evaluation.md](final_evaluation.md); it did not affect fix selection.
The retained change is the deterministic conflict fix and private diagnostics;
the tested prompt expansion was rejected after its mixed live results.

## Root-cause evidence

The read-only audit is reproducible with `python -m scripts.diagnose_quality`.
Hashes of the original final dataset, manifest, report, checkpoint, and retrieval
comparison are recorded in [phase7_4_diagnosis.json](phase7_4_diagnosis.json).
No original final investigation was rerun.

### Conflict handling

All six unsuccessful conflict fixtures returned `central_claim_unverified`, with
both supporting references retrieved and both draft citations retained. The
baseline validator returns `insufficient` for a missing/unverified central claim
before examining `conflict_groups`. That rejection path is confirmed. Retrieval,
tool failure, and rejected quotations do not explain these six outputs.

The original checkpoint omitted the draft central ID and conflict groups. It
cannot establish whether Gemini emitted an empty ID, a nonexistent ID, or valid
conflict groups. The empty-central conflict defect is reproduced independently;
it is not a claim that all six historical drafts contained valid groups.

### Five answerable abstentions

| Case ID suffix | Confirmed signal | Gold support found | Tool / HTTP calls |
| --- | --- | ---: | ---: |
| `5a8109535542995ce29dcba2` | Citation rejection | 2/2 | 2 / 4 |
| `5a8d54b055429941ae14dfa7` | Retrieval miss, then model abstained | 0/2 | 4 / 5 |
| `5ae18f005542997283cd222c` | Model abstained with complete support | 2/2 | 4 / 5 |
| `5a85a4d75542994c784ddb2f` | Citation rejection | 2/2 | 2 / 4 |
| `5ab9703c55429970cfb8eaee` | Model abstained with complete support | 2/2 | 2 / 4 |

For the four complete-support cases, the gold sentences fit inside the 1,200
character tool-message prefixes when reconstructed from the local corpus. No
truncation of those particular sentences was found. The checkpoint does not
retain intermediate model reasoning or original tool-query strings, so the two
remaining abstentions cannot be attributed to a more specific cause.

### Seven withheld citations

| Case ID suffix | Draft / retained | Withheld |
| --- | ---: | ---: |
| `5a8109535542995ce29dcba2` | 2 / 0 | 2 |
| `5ac450345542995c82c4ad2b` | 2 / 1 | 1 |
| `5a85a4d75542994c784ddb2f` | 4 / 0 | 4 |

The baseline retains a claim only if every citation passes. The seven-count gap
therefore includes citations withheld with their claim; it is not a per-quote
proof that all seven were invalid. Rejected quote strings and chunk references
were not saved. Their individual causes (paraphrase, ellipsis, attribution,
unknown chunk, or offset mismatch) are **unrecoverable from that checkpoint**.
The immutable final report's metric is preserved; this qualification explains
its denominator rather than changing its recorded result.

### DHL relationship error

The question asked for a founder whose **business partner** had a son convicted
of manslaughter. The returned central claim answered the founder whose **own
son** had that conviction, selecting Adrian Dalsey instead of Larry Hillblom.
All five gold support references were retrieved and fit within the prompt
prefixes; both accepted quotes came from Adrian Dalsey's paragraph. This is a
confirmed loss of a relationship qualifier and a cross-document premise. Exact
quote matching cannot reject a logically misapplied quotation on its own.

Evidence accumulation already retains chunks across tool calls. A new two-call
regression verifies both premises survive and can be cited; no retrieval
algorithm or evidence-store redesign was necessary.

## Minimal implementation

- An explicitly empty central ID can represent an unresolved conflict only when
  the model supplied a group of at least two distinct, fully quote-verified
  claims and no claims were dropped. A nonempty missing/rejected central ID
  still causes abstention. No conflict is inferred from numbers or keywords.
- A prompt expansion covering relationship roles, chronological changes and
  verbatim quotations was tested, then removed: it did not improve the 20-question
  answer-span score and increased cost. Runtime prompts equal the baseline.
  The rejected candidate is preserved as
  [`eval/quality_prompt_candidate.patch`](../eval/quality_prompt_candidate.patch).
- Exact citation checks retain all previous rules and now expose per-citation
  reason codes. Claims remain atomic: one bad quote still withholds the claim.
- Detailed drafts, tool arguments and validation indices are captured only in
  explicit local evaluation mode. Public response/log allowlists omit them.
  Future private checkpoints can distinguish source attribution, missing chunks,
  malformed references, offsets and non-verbatim quotation failures.
- No automatic quotation replacement or repair call was added. The historical
  quote strings are missing, so a repair policy is not supported by this audit.
  The four-tool/five-HTTP-request limits, configured timeouts, and token limit
  remain in force.

## Independent development data

`eval/quality_dev_manifest.json` freezes 20 unchanged members of the original
200-question development set. Selection uses seed `evidenceai-phase7.4-v1` and
hash ordering within strata: 10 bridge and 10 comparison questions, comprising
eight easy, six medium and six hard cases. The selector never reads final cases.
Local corpus verification found **20/20 cases and 48/48 supporting references**;
the live runner separately requires fresh indexed Frankfurt coverage.

`eval/quality_dev_fixtures.json` contains five new synthetic contradictions and
five controls: different timestamps, different versions, consistent evidence,
missing evidence, and a two-document partner/child relationship. Fixture evidence
is injected locally; it is never written to Supabase. Gold answers and scripted
replay drafts are not passed to Gemini.

## Scripted validator replay

This replay sends identical authored drafts to the validator at baseline commit
`ee9c9c11f90d3083917bea9bf92720ddab23939b` and to the revised validator.
It measures status handling and strict quotation acceptance with known model
outputs. It does not measure Gemini conflict detection or retrieval quality.

| Check | Frozen validator | Revised validator |
| --- | ---: | ---: |
| Empty-central contradictions accepted | 0/5 | 5/5 |
| False conflicts on controls | 0/5 | 0/5 |
| Controls with expected status | 5/5 | 5/5 |
| Correct missing-evidence abstention | 1/1 | 1/1 |
| Retained exact citations | 18/18 | 18/18 |
| Median validator time, local | 0.0131 ms | 0.0179 ms |
| Gemini requests | 0 | 0 |

Timing is from 25 repetitions per fixture and is local validator CPU time. It
does not predict API or Render latency. Machine-readable replay results are in
[quality_dev_replay.json](quality_dev_replay.json).

## Live before/after prompt-candidate comparison

The operator approved 60 new development investigations and at most 300 Gemini
HTTP requests. Each variant uses the same 20 development questions and 10
fixtures. The baseline agent, prompt and validator are loaded from the fixed Git
commit in private evaluator namespaces. Tool/schema/client dependencies must
match the baseline. Production modules are not globally monkeypatched. The live
`after` run tested the combined validator fix and expanded prompts; that prompt
candidate is not the retained runtime.

The new runner shares the existing rolling ledger and uses separate Git-ignored
development checkpoints. It refuses uncertain reservations and changed input,
model, code or configuration fingerprints. A tracked client enforces five actual
HTTP attempts per investigation and preserves earlier request counts if a later
call fails. Quota errors stop the run. A process-only budget of 120 supplies room
for 46 prior reservations plus the authorized 60; `.env` and Render stay intact.

| Metric | Frozen baseline, live | Expanded prompt candidate, live |
| --- | ---: | ---: |
| Completed investigations | 30/30 | 30/30 |
| Conflict detection | 3/5 (60%) | 5/5 (100%) |
| False conflicts | 0/25 | 0/25 |
| Correct missing-evidence abstentions | 1/1 | 1/1 |
| Development multi-hop answer-span correctness | 9/20 (45%) | 9/20 (45%) |
| Incorrect abstentions on answerable dev cases | 3/20 | 5/20 |
| Partner/child control, central-claim span score | 1/1 | 0/1 |
| Retained / drafted citations | 45/46 (97.826%) | 44/45 (97.778%) |
| Retrieved development support references | 43/48 | 43/48 |
| Median investigation latency | 4.174 s | 4.821 s |
| p95 investigation latency, nearest rank | 7.534 s | 7.715 s |
| Gemini HTTP requests | 109 | 119 |
| Investigation errors | 0 | 0 |

The two runs consumed **228/300 authorized requests and 60/60 investigations**.
No quota/rate-limit error occurred; every investigation used at most five HTTP
requests. The shared ledger grew from 46 to 106 reservations without being reset.
The process budget was restored; local `.env` remains at 60 and Render was not
changed. Both runs used `gemini-3.5-flash-lite`.

The fresh read-only Frankfurt gate verified project `nldnpqhqrfwjgxcqeuru`,
50,000 documents, 20/20 selected questions, and 48/48 exact support references
from 40 source/chunk rows. See
[quality_dev_indexed_coverage.json](quality_dev_indexed_coverage.json).

Answer correctness is the unchanged **central-claim gold-span proxy**. Two dev
scores improved and two regressed; the net stayed 9/20. Some changes were
central-claim selection rather than different facts: the political-party example
already contained the gold party in a secondary claim before, and the partner
control still named Neri in its first premise after, but selected the other
premise as central. These are scoring/answer-focus failures and cannot all be
called factual reasoning errors. No gold or scoring rules were changed.

One new baseline citation combined separated source spans with an inserted
`...`; strict matching rejected it. The prompt candidate's sole failed quote
referenced a chunk ID that was not retrieved. These new observed reasons do not
recover the missing reasons for the seven historical withheld citations.

The new baseline also captured valid conflict groups with an empty central ID
for `quality-conflict-sealed-crates` and `quality-conflict-station-operator`;
both were rejected by the frozen validator despite two exact quotes. This
directly confirms the defect on independent live drafts.

The live candidate cost ten more requests, had a slower median, and showed no
aggregate answer-score improvement. Its broad prompt changes were therefore
not retained. Before/after calls were sequential on this workstation, so latency
differences may also include network/provider variability; these are not Render
latency or memory measurements.

## Retained minimal fix: replay of actual baseline drafts

`python -m scripts.replay_quality_baseline` reconstructed the saved retrieved
paragraphs from the canonical local corpus (exact equality required), reproduced
all 30 original baseline statuses and retained-citation counts, and then applied
the revised validator to those same drafts. It made no model requests and changed
only the two unresolved-conflict statuses above.

| Metric on the same saved live drafts | Frozen validator | Retained validator |
| --- | ---: | ---: |
| Conflicts recognized | 3/5 | 5/5 |
| False conflicts | 0/25 | 0/25 |
| Correct missing-evidence abstention | 1/1 | 1/1 |
| Dev central-claim answer-span score | 9/20 | 9/20 |
| Partner/child control span score | 1/1 | 1/1 |
| Retained citations | 45/46 | 45/46 |
| Additional Gemini requests | 0 | 0 |

This isolates the deterministic fix using actual model drafts; it is not a fresh
live end-to-end run of the retained build. Runtime prompts and generation limits
have been restored to the baseline. Machine-readable evidence is in
[quality_dev_retained_replay.json](quality_dev_retained_replay.json), the live
[before summary](quality_dev_before_summary.json),
[candidate summary](quality_dev_after_summary.json), and
[combined comparison](quality_dev_comparison.json). Per-case drafts and quotes
remain in ignored local checkpoint files.

## Limitations and verification

- The DHL case was diagnosed but not rerun. No multi-hop reasoning improvement
  is claimed; role reasoning and central-claim selection still need development.
- Contradiction semantics still originate in the model's groups. Exact quotation
  presence and group membership do not prove incompatibility or entailment.
- Five contradictions, five controls and twenty questions are a small development
  sample. Zero observed false conflicts is not a general false-positive guarantee.
- The original seven withheld quote strings remain unavailable; the new detailed
  diagnostics support future investigations without inventing historical causes.
- No automatic repair, extra model call, new infrastructure, corpus write, schema
  change or deployment was introduced. The retained build has unit and saved-draft
  verification. A later approved run of only the seven final conflict fixtures,
  after the Gemini network probe passed, returned the expected conflict status
  in 7/7 cases with 21 requests and 14/14 exact-quote checks; it was not used to
  select or tune the fix. The first attempt's network failures are footnoted in
  `final_evaluation.md`.
- Complete local suite: **267 passed**. The original 45-row result checkpoint,
  dataset and baseline metrics remain unchanged. The report's baseline content
  is hash-checked after removing only the separately approved post-hoc block.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_quality_dev
.\.venv\Scripts\python.exe -m scripts.diagnose_quality
.\.venv\Scripts\python.exe -m scripts.audit_quality_dev
.\.venv\Scripts\python.exe -m scripts.evaluate_quality_dev
.\.venv\Scripts\python.exe -m scripts.evaluate_quality_dev --plan
.\.venv\Scripts\python.exe -m scripts.replay_quality_baseline
.\.venv\Scripts\python.exe -m scripts.summarize_quality_dev
.\.venv\Scripts\python.exe -m pytest -q
```

The authorized 60-investigation allowance has been used; the commands below
require new explicit quota approval to make further calls. To reproduce the
rejected prompt experiment, use an isolated checkout of this milestone and apply
`git apply --unidiff-zero --ignore-space-change eval/quality_prompt_candidate.patch`
there (the patch has zero context; the whitespace option handles Windows line
endings). Preserve existing result
files and their fingerprints; the CLI refuses to mix results from changed code.
Save and restore any process environment override in `try/finally`; never clear
the shared ledger.

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_quality_dev --live --variant before --confirm-api-usage --max-investigations 30
.\.venv\Scripts\python.exe -m scripts.evaluate_quality_dev --live --variant after --confirm-api-usage --max-investigations 30
```

Run the second command only if the first completed without a quota/error stop.
There is no final-set rerun or deployment command in this workflow.

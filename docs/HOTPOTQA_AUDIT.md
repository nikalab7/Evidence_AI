# HotpotQA Corpus Audit

This is the initial HotpotQA source audit, performed before the full corpus
was indexed. It streams a pinned dataset revision and records aggregate
counts in `reports/hotpotqa_audit.json`. The later 50,000-document ingestion
and final evaluation are documented separately.

## Reproducible source

- Dataset: [`hotpotqa/hotpot_qa`](https://huggingface.co/datasets/hotpotqa/hotpot_qa)
- Revision: `1908d6afbbead072334abe2965f91bd2709910ab`
- Configuration: `distractor`
- Splits: `train` and `validation`
- License: CC BY-SA 4.0; retain dataset attribution when publishing derived work.

The dataset card describes context passages as titles plus sentence lists and
supporting facts as title plus sentence index. The audit validates both pieces
of that reference before counting evidence coverage.

## Reproduce

```powershell
python -m pip install -r requirements-audit.txt
python -m scripts.audit_hotpotqa --max-rows 100 --output "$env:TEMP\hotpotqa-audit-smoke.json"
python -m scripts.audit_hotpotqa --output reports\hotpotqa_audit.json
```

The audit dependency is separate from Render's runtime dependencies. Streaming
avoids saving the raw rows to the repository. Temporary Hub cache files are
removed when the command finishes.

## Counting rules

- A candidate record is one context paragraph.
- A unique record is the SHA-256 hash of its normalized title and the joined
  normalized paragraph sentences. Normalization uses Unicode NFKC, casefolding,
  and collapsed whitespace.
- Including the title in the key keeps identical paragraph text under
  different source titles as distinct records.
- This is normalized exact deduplication. Near-duplicate or paraphrased
  paragraphs are not merged, so the count does not claim semantic independence.
- Validation evidence is checked by matching the normalized supporting title
  and exact normalized sentence text in the same sentence index.
- Train-only coverage estimates how much validation evidence exists if the
  knowledge corpus contains only training contexts. Combined coverage includes
  validation contexts and measures source availability, not retrieval quality.

Exact evidence presence does not establish factual entailment. The audit does
not evaluate retrieval or answer correctness. Coverage is measured at source
paragraph level; the final chunking/indexing stage must confirm that each
selected support sentence remains linked to an indexed source chunk.

## Recorded result

The full scan, counts, split duplicates, and evidence coverage are in
[`reports/hotpotqa_audit.json`](../reports/hotpotqa_audit.json). The scan found
more than 50,000 unique candidate records:

| Split/source pool | Context paragraph occurrences | Unique title+paragraph records | Duplicate occurrences |
| --- | ---: | ---: | ---: |
| Train | 899,667 | 482,021 | 417,646 |
| Validation | 73,700 | 66,581 | 7,119 |
| Train + validation union | 973,367 | 507,494 | 465,873 |

There are 41,108 exact records shared across the two splits and no repeated
question IDs between splits. The union's 465,873 duplicate occurrences consist
of train repeats, validation repeats, and cross-split repeats.

Validation contains 18,005 supporting-fact references. One reference in record
`5ae61bfd5542992663a4f261` does not resolve to a non-empty sentence in its own
context, so source-context integrity is 18,004 / 18,005 (99.994%). In the
train-only context corpus, 13,198 / 18,004 valid support sentences are present
(73.31%), and all support sentences are present for 4,247 / 7,404 valid
questions (57.36%). The train+validation union contains the validation source
contexts, so its 99.994% evidence presence is a source-availability check, not
a retrieval-quality result.

The subsequent content-hash selection is documented in
[`reports/corpus_audit.json`](../reports/corpus_audit.json). It selected
50,000 unique paragraph texts and checked their supporting evidence.
The generated `data/corpus.jsonl` remains local and Git-ignored.
The first Phase 1C pilot indexed 100 documents. Later, Phase 5 indexed
the full 50,000 records; see the
[capacity report](../reports/capacity_50k.md).

The validation split contains 5,918 bridge and 1,487 comparison questions, all
marked `hard` in this dataset revision. It does not supply absent-answer,
conflicting, or simple-question cases. Those categories were subsequently
included in the separate 45-case
[final evaluation](../EVALUATION_REPORT.md).

The staged capacity checks were later completed during the full ingestion.
This file retains the original dataset-scan measurements.

# HotpotQA Corpus Build

## Reproducible source and sampling

- Dataset: `hotpotqa/hotpot_qa`, `distractor`, train split.
- Dataset revision: `1908d6afbbead072334abe2965f91bd2709910ab`.
- Dataset library: `datasets==4.8.4` from `requirements-audit.txt`.
- Sampling seed: `42`.
- Each question is ranked by SHA-256 of `seed + NUL + question_id`; the lowest
  ranks are selected independently within bridge/comparison and easy/medium/hard.
- The 200 retrieval questions and 40 candidate questions are disjoint. Per
  type and level, the dev quotas are 34/33/33 and candidate quotas are 7/7/6.

## Build and verify

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-audit.txt
.\.venv\Scripts\python.exe scripts\build_corpus.py
.\.venv\Scripts\python.exe -m pytest -q
```

The default command streams the pinned train split twice. It writes the compact
audit report and 40-line `eval/eval_candidates.jsonl`. The larger outputs were
materialized with `--write-large-files`: `eval/retrieval_dev.jsonl` is committed,
while `data/corpus.jsonl` is local and Git-ignored. To regenerate them, run:

```powershell
.\.venv\Scripts\python.exe scripts\build_corpus.py --write-large-files
```

The command records selected question IDs, dataset/library versions, corpus and
evaluation JSONL SHA-256 hashes, counts, duplicate totals, collision examples,
and evidence coverage in `reports/corpus_audit.json`. `data/corpus.jsonl` is
ignored by Git. Dataset cache files stay under the ignored `data/cache/` path.

## Identity and evidence rules

Each selected question must have ten valid context paragraphs and resolvable
supporting title/sentence references. The builder adds all 2,400 selected
question paragraphs first, then scans other train questions in source order
until it has 50,000 unique normalized paragraph texts. Text normalization uses
Unicode NFKC, casefolding, and collapsed whitespace; SHA-256 of this text is
the stable document ID. Titles remain source metadata and do not decide content
identity.

Identical content under a new title is deduplicated by hash while its title and
sentence variant are retained. A repeated normalized title with different
content hashes is a collision; each version remains a separate document. The
coverage check requires every selected supporting title and exact normalized
support sentence to exist under that title. Coverage does not establish factual
entailment. Estimated tokens are approximate characters divided by four.

The 40 HotpotQA cases are candidates, not a completed final evaluation set. The
plan later chooses 25 multi-hop cases and adds five single-hop, eight
unanswerable, and seven conflicting cases.

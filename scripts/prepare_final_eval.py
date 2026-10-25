"""Build a fixed, evidence-checked answer-evaluation set without DB writes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from app.ingestion.corpus_core import normalize_text


ROOT = Path(__file__).resolve().parent.parent
CANDIDATES = ROOT / "eval" / "eval_candidates.jsonl"
CORPUS = ROOT / "data" / "corpus.jsonl"
OUTPUT = ROOT / "eval" / "final_answer_eval.jsonl"
MANIFEST = ROOT / "eval" / "final_answer_eval_manifest.json"
SELECTION_SEED = "evidenceai-final-2026-10-25"
QUOTAS = {
    "bridge/easy": 3,
    "bridge/medium": 4,
    "bridge/hard": 4,
    "comparison/easy": 4,
    "comparison/medium": 5,
    "comparison/hard": 5,
}


SINGLE_HOP = [
    {
        "case_id": "single-maile-meloy-birth-date",
        "question": "What is the birth date of American fiction writer Maile Meloy?",
        "gold_answer": "January 1, 1972",
        "source_question_id": "5a7a892a55429941d65f268d",
        "support_title": "Maile Meloy",
        "support_sentence": "Maile Meloy (born January 1, 1972) is an American fiction writer.",
    },
    {
        "case_id": "single-b2fh-publication-year",
        "question": "In what year was the B2FH paper published in Reviews of Modern Physics?",
        "gold_answer": "1957",
        "source_question_id": "5ab3026c55429976abd1bc1c",
        "support_title": "B2FH paper",
        "support_sentence": "The BFH paper, named after the initials of the authors of the paper, Margaret Burbidge, Geoffrey Burbidge, William Fowler, and Fred Hoyle, is a landmark paper of stellar physics published in \"Reviews of Modern Physics\" in 1957.",
    },
    {
        "case_id": "single-mh17-casualties",
        "question": "How many passengers and crew were killed when Malaysia Airlines Flight 17 was shot down?",
        "gold_answer": "283 passengers and 15 crew",
        "source_question_id": "5ab6d9295542995eadef00c4",
        "support_title": "Malaysia Airlines Flight 17",
        "support_sentence": "Malaysia Airlines Flight 17 (MH17/MAS17) was a scheduled passenger flight from Amsterdam to Kuala Lumpur that was shot down on 17 July 2014 while flying over eastern Ukraine, killing all 283 passengers and 15 crew on board.",
    },
    {
        "case_id": "single-stiff-little-fingers-origin",
        "question": "From which city and region are Stiff Little Fingers?",
        "gold_answer": "Belfast, Northern Ireland",
        "source_question_id": "5ab2fc3355429976abd1bbf0",
        "support_title": "Stiff Little Fingers",
        "support_sentence": "Stiff Little Fingers are a punk rock band from Belfast, Northern Ireland.",
    },
    {
        "case_id": "single-tyronn-lue-birth-date",
        "question": "What is Tyronn Lue's date of birth?",
        "gold_answer": "May 3, 1977",
        "source_question_id": "5a7302895542992359bc31fc",
        "support_title": "Tyronn Lue",
        "support_sentence": "Tyronn Jamar Lue ( , born May 3, 1977) is an American former professional basketball player and the current head coach of the Cleveland Cavaliers of the National Basketball Association (NBA).",
    },
]


UNANSWERABLE = [
    ("unanswerable-01", "QX-EMBER-7719", "How many amber drones departed from the QX-EMBER-7719 station on 17 May?"),
    ("unanswerable-02", "NIMBUS-ORCHID-6042", "What was the launch date of the NIMBUS-ORCHID-6042 observatory?"),
    ("unanswerable-03", "VARN-KESTREL-8831", "Which company manufactured the VARN-KESTREL-8831 engine?"),
    ("unanswerable-04", "LUMEN-OTTER-2917", "How many researchers worked at the LUMEN-OTTER-2917 laboratory?"),
    ("unanswerable-05", "CIRRUS-THISTLE-5408", "What was the measured rainfall at CIRRUS-THISTLE-5408 on 2 April?"),
    ("unanswerable-06", "TIDAL-MARBLE-1673", "Who designed the TIDAL-MARBLE-1673 bridge?"),
    ("unanswerable-07", "CINDER-FOXGLOVE-9921", "What is the operating capacity of the CINDER-FOXGLOVE-9921 reactor?"),
    ("unanswerable-08", "MOSAIC-ARROW-3486", "In which year did the MOSAIC-ARROW-3486 archive open?"),
]


CONFLICTS = [
    ("conflict-01", "At 14:00 UTC, was payment processing available or unavailable?",
     "At 14:00 UTC, payment processing was unavailable.",
     "At 14:00 UTC, payment processing remained available."),
    ("conflict-02", "How many jobs per minute did the Orion queue process?",
     "The Orion queue processed 120 jobs per minute.",
     "The Orion queue processed 85 jobs per minute."),
    ("conflict-03", "What temperature did the North Vault maintain at noon?",
     "At noon, the North Vault temperature was 18 degrees Celsius.",
     "At noon, the North Vault temperature was 24 degrees Celsius."),
    ("conflict-04", "At what time was the Atlas batch completed?",
     "The Atlas batch completed at 09:15 UTC.",
     "The Atlas batch completed at 09:45 UTC."),
    ("conflict-05", "What is the retention period for Raven records?",
     "Raven records are retained for 30 days.",
     "Raven records are retained for 90 days."),
    ("conflict-06", "How many units were in the Delta inventory at close?",
     "The Delta inventory contained 64 units at close.",
     "The Delta inventory contained 46 units at close."),
    ("conflict-07", "Was the Vega maintenance task complete by 24 October 2026?",
     "The Vega maintenance task was completed on 23 October 2026.",
     "As of 24 October 2026, the Vega maintenance task was not complete."),
]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError(f"JSONL row {line_number} must be an object")
            rows.append(item)
    return rows


def candidate_digest(candidate: MappingLike) -> str:
    return hashlib.sha256(
        f"{SELECTION_SEED}\0{candidate['question_id']}".encode("utf-8")
    ).hexdigest()


MappingLike = dict[str, Any]


def corpus_pairs(path: Path) -> tuple[set[tuple[str, str]], str]:
    """Return title/sentence pairs that occur in canonical text and the corpus hash."""
    pairs: set[tuple[str, str]] = set()
    corpus_hash = hashlib.sha256()
    absent_tokens = {token for _, token, _ in UNANSWERABLE}
    token_hits: set[str] = set()
    with path.open("rb") as raw:
        for line in raw:
            corpus_hash.update(line)
            row = json.loads(line)
            text = row.get("text", "")
            normalized_text = normalize_text(text) if isinstance(text, str) else ""
            folded = line.decode("utf-8").casefold()
            token_hits.update(token for token in absent_tokens if token.casefold() in folded)
            variants = row.get("source_variants", [])
            for variant in variants if isinstance(variants, list) else []:
                if not isinstance(variant, dict):
                    continue
                title = variant.get("title")
                sentences = variant.get("sentences") or []
                if not isinstance(title, str) or not isinstance(sentences, list):
                    continue
                for sentence in sentences:
                    if isinstance(sentence, str) and normalize_text(sentence) in normalized_text:
                        pairs.add((normalize_text(title), normalize_text(sentence)))
    if token_hits:
        raise ValueError("synthetic unanswerable identifier unexpectedly occurs in corpus")
    return pairs, corpus_hash.hexdigest()


def _single_hop_cases(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_question = {item["question_id"]: item for item in candidates}
    records = []
    for item in SINGLE_HOP:
        source = by_question[item["source_question_id"]]
        support = next((fact for fact in source["supporting_evidence"]
                        if normalize_text(fact["title"]) == normalize_text(item["support_title"])
                        and normalize_text(fact["sentence"]) == normalize_text(item["support_sentence"])), None)
        if support is None:
            raise ValueError(f"single-hop support is not in candidate {item['source_question_id']}")
        records.append({
            "case_id": item["case_id"], "category": "single_hop",
            "execution_mode": "live", "question": item["question"],
            "gold_answer": item["gold_answer"], "expected_status": "answered",
            "supporting_evidence": [support], "evidence_scope": "single_document",
            "derived_from_question_id": item["source_question_id"],
        })
    return records


def _conflict_cases() -> list[dict[str, Any]]:
    rows = []
    for case_id, question, left, right in CONFLICTS:
        docs = []
        support = []
        for suffix, sentence in (("a", left), ("b", right)):
            title = f"Synthetic {case_id} Report {suffix.upper()}"
            doc_id = f"fixture-{case_id}-{suffix}"
            docs.append({
                "chunk_id": f"fixture-chunk-{case_id}-{suffix}",
                "doc_id": doc_id, "source_id": f"fixture-source-{case_id}-{suffix}",
                "title": title, "sentence": sentence,
            })
            support.append({"title": title, "sentence": sentence})
        rows.append({
            "case_id": case_id, "category": "conflicting",
            "execution_mode": "fixture", "question": question,
            "gold_answer": "The retrieved sources conflict.",
            "expected_status": "conflicting", "supporting_evidence": support,
            "fixture_evidence": docs, "evidence_scope": "synthetic_fixture_only",
        })
    return rows


def build_dataset(candidates: list[dict[str, Any]], corpus_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(candidates) != 40 or len({row.get("question_id") for row in candidates}) != 40:
        raise ValueError("expected exactly 40 unique held-out candidate rows")
    used_pairs = {
        (normalize_text(fact["title"]), normalize_text(fact["sentence"]))
        for item in SINGLE_HOP for fact in candidates_by_id(candidates)[item["source_question_id"]]["supporting_evidence"]
        if normalize_text(fact.get("title", "")) == normalize_text(item["support_title"])
        and normalize_text(fact.get("sentence", "")) == normalize_text(item["support_sentence"])
    }
    selected: list[dict[str, Any]] = []
    for stratum, quota in QUOTAS.items():
        options = [row for row in candidates
                   if f"{row.get('type')}/{row.get('level')}" == stratum
                   and not any((normalize_text(fact["title"]), normalize_text(fact["sentence"])) in used_pairs
                               for fact in row.get("supporting_evidence", []))]
        options.sort(key=lambda row: candidate_digest(row))
        if len(options) < quota:
            raise ValueError(f"not enough disjoint candidate cases in {stratum}")
        for row in options[:quota]:
            if len({normalize_text(fact["title"]) for fact in row["supporting_evidence"]}) < 2:
                raise ValueError(f"selected HotpotQA case is not cross-document: {row['question_id']}")
            selected.append({
                "case_id": f"hotpotqa-{row['question_id']}",
                "category": "multi_hop", "execution_mode": "live",
                "question": row["question"], "gold_answer": row["answer"],
                "expected_status": "answered", "supporting_evidence": row["supporting_evidence"],
                "evidence_scope": "cross_document", "question_type": row["type"],
                "difficulty": row["level"], "source_question_id": row["question_id"],
                "dataset": row["dataset"], "revision": row["revision"],
            })
    single_hop = _single_hop_cases(candidates)
    pairs, corpus_sha256 = corpus_pairs(corpus_path)
    answerable = selected + single_hop
    missing = [case["case_id"] for case in answerable
               if any((normalize_text(fact["title"]), normalize_text(fact["sentence"])) not in pairs
                      for fact in case["supporting_evidence"])]
    if missing:
        raise ValueError("supporting evidence missing from local corpus: " + ", ".join(missing))

    unanswerable = [{
        "case_id": case_id, "category": "unanswerable", "execution_mode": "live",
        "question": question, "gold_answer": "Insufficient evidence in the indexed corpus.",
        "expected_status": "insufficient", "supporting_evidence": [],
        "evidence_scope": "no_known_corpus_evidence", "synthetic_identifier": token,
    } for case_id, token, question in UNANSWERABLE]
    records = [*selected, *single_hop, *unanswerable, *_conflict_cases()]
    if len(records) != 45 or len({row["case_id"] for row in records}) != 45:
        raise ValueError("final answer dataset must contain 45 unique cases")
    summary = {
        "seed": SELECTION_SEED,
        "stratum_quotas": QUOTAS,
        "candidate_ids_selected": [row["source_question_id"] for row in selected],
        "category_counts": {category: sum(row["category"] == category for row in records)
                            for category in ("multi_hop", "single_hop", "unanswerable", "conflicting")},
        "live_case_count": sum(row["execution_mode"] == "live" for row in records),
        "fixture_only_case_count": sum(row["execution_mode"] == "fixture" for row in records),
        "answerable_support_references": sum(len(row["supporting_evidence"]) for row in answerable),
        "local_corpus_support_coverage_percent": 100.0,
        "corpus_jsonl_sha256": corpus_sha256,
    }
    return records, summary


def candidates_by_id(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["question_id"]: row for row in candidates}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=CANDIDATES)
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    candidates = read_jsonl(args.candidates)
    audit_path = ROOT / "reports" / "corpus_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    actual_sha = hashlib.sha256(args.candidates.read_bytes()).hexdigest()
    if actual_sha != audit["eval_candidates_jsonl_sha256"]:
        raise SystemExit("candidate dataset hash differs from the audited held-out pool")
    records, summary = build_dataset(candidates, args.corpus)
    dev_rows = read_jsonl(ROOT / "eval" / "retrieval_dev.jsonl")
    final_source_ids = {
        source_id for row in records
        for source_id in (row.get("source_question_id"), row.get("derived_from_question_id"))
        if source_id
    }
    if final_source_ids & {row.get("question_id") for row in dev_rows}:
        raise ValueError("final answer questions overlap the retrieval development set")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                                           for row in records), encoding="utf-8")
    output_sha256 = hashlib.sha256(args.output.read_bytes()).hexdigest()
    candidate_sha256 = hashlib.sha256(args.candidates.read_bytes()).hexdigest()
    manifest = {
        "status": "passed", "selection_seed": summary["seed"],
        "selection_algorithm": "rank by SHA-256(seed + NUL + question_id) within type/difficulty strata after reserving the five single-hop evidence pairs",
        "candidate_pool_sha256": candidate_sha256,
        "retrieval_dev_sha256": hashlib.sha256((ROOT / "eval" / "retrieval_dev.jsonl").read_bytes()).hexdigest(),
        "corpus_jsonl_sha256": summary["corpus_jsonl_sha256"],
        "final_dataset_sha256": output_sha256,
        "final_dataset_path": args.output.relative_to(ROOT).as_posix() if args.output.is_relative_to(ROOT) else str(args.output),
        "case_count": len(records), "category_counts": summary["category_counts"],
        "live_case_count": summary["live_case_count"],
        "fixture_only_case_count": summary["fixture_only_case_count"],
        "answerable_support_references": summary["answerable_support_references"],
        "local_corpus_support_coverage_percent": summary["local_corpus_support_coverage_percent"],
        "unanswerable_identifiers_absent_from_corpus": len(UNANSWERABLE),
        "candidate_stratum_quotas": summary["stratum_quotas"],
        "selected_hotpotqa_question_ids": summary["candidate_ids_selected"],
        "retrieval_dev_question_ids_disjoint": True,
        "conflict_evidence": "synthetic fixture only; not ingested into Supabase",
    }
    manifest_path = MANIFEST if args.output == OUTPUT else args.output.with_name("final_answer_eval_manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "manifest": str(manifest_path), **manifest},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Verify selected development evidence against the local corpus without a database."""

import hashlib
import json

from app.evaluation.quality_dev import ROOT, load_cases
from app.ingestion.corpus_core import normalize_text


def main():
    cases, manifest = load_cases()
    live = [c for c in cases if c["execution_mode"] == "live"]
    required = {(normalize_text(f["title"]), normalize_text(f["sentence"]))
                for c in live for f in c["supporting_evidence"]}
    by_title = {}
    for title, sentence in required:
        by_title.setdefault(title, set()).add(sentence)
    found = set()
    digest = hashlib.sha256()
    with (ROOT / "data/corpus.jsonl").open("rb") as source:
        for line in source:
            digest.update(line)
            doc = json.loads(line)
            titles = [doc["title"], *[v["title"] for v in doc.get("source_variants", [])]]
            for title in {normalize_text(t) for t in titles} & by_title.keys():
                text = normalize_text(doc["text"])
                found.update((title, sentence) for sentence in by_title[title] if sentence in text)
    references = [(normalize_text(f["title"]), normalize_text(f["sentence"]))
                  for c in live for f in c["supporting_evidence"]]
    output = {
        "source": "local corpus only; indexed database coverage is checked separately before live calls",
        "questions": len(live), "eligible_questions": sum(
            all((normalize_text(f["title"]), normalize_text(f["sentence"])) in found
                for f in c["supporting_evidence"]) for c in live),
        "support_references": len(references),
        "support_references_found": sum(pair in found for pair in references),
        "unique_support_pairs": len(required), "unique_support_pairs_found": len(found),
        "corpus_sha256": digest.hexdigest(), "questions_sha256": manifest["questions_sha256"],
    }
    (ROOT / "reports/quality_dev_support_audit.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(output, sort_keys=True))
    if found != required:
        raise SystemExit("development supporting evidence is incomplete")


if __name__ == "__main__":
    main()

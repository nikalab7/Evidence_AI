from app.ingestion.corpus_core import content_hash, coverage_report, normalize_text
from app.ingestion.corpus_store import CorpusStore
from app.ingestion.hotpotqa_corpus import build_hotpotqa_corpus


def _question():
    return {
        "id": "q1", "question": "Where is the fact?", "answer": "Somewhere",
        "type": "bridge", "level": "easy",
        "context": {
            "title": ["Alpha", "Beta"],
            "sentences": [["Alpha fact.", "Alpha extra."], ["Beta fact."]],
        },
        "supporting_facts": {"title": ["Alpha", "Beta"], "sent_id": [0, 0]},
    }


def test_normalization_and_content_hash_ignore_case_and_whitespace():
    assert normalize_text("  Ｃafé\tAND  Tea  ") == "café and tea"
    assert content_hash(" Evidence\n from a source ") == content_hash("evidence from a source")


def test_duplicate_detection_uses_content_hash_and_keeps_title_collisions():
    corpus = CorpusStore("pinned-revision")
    assert corpus.add_paragraph("Article", ["Same content"])
    assert not corpus.add_paragraph(" article ", [" same   content "])
    assert not corpus.add_paragraph("Alias", ["Same", "content"])
    assert corpus.add_paragraph("Article", ["A different version"])

    stats = corpus.stats()
    assert stats["unique_content_documents"] == 2
    assert stats["duplicates_skipped_by_title"] == 1
    assert stats["duplicates_skipped_by_hash"] == 1
    assert stats["title_collision_count"] == 1
    assert stats["title_collision_examples"][0]["version_count"] == 2
    first = next(doc for doc in corpus.documents.values() if doc["text"] == "Same content")
    aliases = {item["title"].strip().lower() for item in first["source_variants"]}
    assert aliases == {"article", "alias"}


def test_coverage_checks_supporting_titles_and_sentences_on_tiny_fixture():
    question = _question()
    corpus = CorpusStore("pinned-revision")
    for title, sentences in zip(question["context"]["title"], question["context"]["sentences"]):
        corpus.add_paragraph(title, sentences)
    coverage = coverage_report([question], corpus.documents.values())
    assert coverage["supporting_title_coverage_percent"] == 100.0
    assert coverage["supporting_sentence_coverage_percent"] == 100.0
    assert coverage["questions_with_invalid_support"] == 0

    missing = CorpusStore("pinned-revision")
    missing.add_paragraph("Alpha", ["Alpha fact.", "Alpha extra."])
    partial = coverage_report([question], missing.documents.values())
    assert partial["supporting_title_coverage_percent"] == 50.0
    assert partial["supporting_sentence_coverage_percent"] == 50.0


def test_builder_applies_fixed_strata_and_keeps_support_first(tmp_path):
    rows = []
    for kind in ("bridge", "comparison"):
        for level, count in zip(("easy", "medium", "hard"), (41, 40, 39)):
            for index in range(count):
                question_id = f"{kind}-{level}-{index}"
                titles = [f"{question_id}-title-{part}" for part in range(10)]
                sentences = [[f"{question_id} unique evidence {part}."] for part in range(10)]
                rows.append({
                    "id": question_id, "question": f"Question {question_id}?", "answer": "Answer",
                    "type": kind, "level": level,
                    "context": {"title": titles, "sentences": sentences},
                    "supporting_facts": {"title": [titles[0]], "sent_id": [0]},
                })
    report, corpus, dev, candidates = build_hotpotqa_corpus(
        lambda *args, **kwargs: rows, "4.8.4", 42, tmp_path / "cache",
    )
    assert len(dev) == 200 and len(candidates) == 40
    assert report["question_sets_disjoint"] is True
    assert report["selected_context_paragraphs"] == 2400
    assert len(corpus.documents) == 2400
    assert report["evidence_coverage"]["combined"]["supporting_sentence_coverage_percent"] == 100.0
    assert report["status"] == "failed"  # Fixture is intentionally below the 50,000-document gate.

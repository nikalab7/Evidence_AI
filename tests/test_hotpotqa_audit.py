from app.ingestion.hotpotqa_audit import audit_hotpotqa_splits, normalize_text


def test_normalization_collapses_unicode_case_and_whitespace():
    assert normalize_text("  Ｃafé\tAND  Tea  ") == "café and tea"


def test_audit_counts_unique_title_text_records_and_validation_evidence():
    train_rows = [
        {
            "id": "train-1",
            "context": {
                "title": ["Article A", "Article B"],
                "sentences": [["Alpha fact.", "Second sentence."], ["Shared text."]],
            },
        },
        {
            "id": "train-2",
            "context": {
                "title": ["article a"],
                "sentences": [[" ALPHA fact.  ", "second   sentence."]],
            },
        },
        {
            "id": "train-3",
            "context": {"title": ["Article C"], "sentences": [["Shared text."]]},
        },
    ]
    validation_rows = [
        {
            "id": "valid-1",
            "type": "bridge",
            "level": "easy",
            "context": {"title": ["ARTICLE A"], "sentences": [["alpha fact.", "SECOND SENTENCE."]]},
            "supporting_facts": {"title": ["Article A", "Article A"], "sent_id": [0, 1]},
        },
        {
            "id": "valid-2",
            "type": "comparison",
            "level": "hard",
            "context": {"title": ["Article A"], "sentences": [["Alpha fact."]]},
            "supporting_facts": {"title": ["Missing article"], "sent_id": [0]},
        },
    ]

    report = audit_hotpotqa_splits(train_rows, validation_rows)

    assert report["train"]["unique_document_records"] == 3
    assert report["train"]["duplicate_document_occurrences"] == 1
    assert report["validation"]["unique_document_records"] == 2
    assert report["combined_context_corpus"]["unique_document_records"] == 4
    assert report["combined_context_corpus"]["duplicate_document_occurrences"] == 2
    evidence = report["validation"]
    assert evidence["supporting_fact_items"] == 3
    assert evidence["valid_supporting_fact_items_in_validation_context"] == 2
    assert evidence["supporting_fact_items_found_in_train_contexts"] == 2
    assert evidence["validation_context_integrity"] == 2 / 3
    assert evidence["supporting_fact_item_train_coverage"] == 1.0
    assert evidence["complete_question_train_coverage"] == 1.0
    assert evidence["invalid_supporting_fact_examples"] == [{
        "question_id": "valid-2",
        "reason": "support_title_missing_from_context",
    }]
    assert "Alpha fact" not in repr(report)
    assert report["combined_context_corpus"]["validation_support_item_presence"] == 2 / 3
    assert report["combined_context_corpus"]["validation_questions_with_valid_context_support"] == 0.5


def test_malformed_context_and_support_arrays_are_counted():
    report = audit_hotpotqa_splits(
        [{"id": "train", "context": {"title": ["A"], "sentences": []}}],
        [{
            "id": "valid", "context": {"title": [], "sentences": []},
            "supporting_facts": {"title": ["A"], "sent_id": []},
        }],
    )

    assert report["train"]["malformed_context_rows"] == 1
    assert report["validation"]["malformed_supporting_fact_rows"] == 1

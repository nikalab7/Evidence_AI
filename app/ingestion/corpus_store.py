"""Content-addressed corpus store with title alias and collision accounting."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from statistics import mean, median
from typing import Any

from app.ingestion.corpus_core import content_hash, normalize_text


SOURCE_URL = "https://huggingface.co/datasets/hotpotqa/hotpot_qa"


class CorpusStore:
    """Merge identical normalized text while retaining each title/sentence version."""

    def __init__(self, revision: str):
        self.revision = revision
        self.documents: dict[str, dict[str, Any]] = {}
        self._variants: dict[str, set[tuple[str, tuple[str, ...]]]] = defaultdict(set)
        self._title_hashes: dict[str, set[str]] = defaultdict(set)
        self._title_labels: dict[str, str] = {}
        self.paragraph_occurrences = 0
        self.duplicates_by_title = 0
        self.duplicates_by_hash = 0
        self.empty_paragraphs = 0

    def add_paragraph(self, title: str, sentences: list[str]) -> bool:
        """Add a paragraph; return true only when its normalized content is new."""
        text = " ".join(sentences).strip()
        normalized_title = normalize_text(title)
        digest = content_hash(text)
        if not normalized_title or not normalize_text(text):
            self.empty_paragraphs += 1
            return False
        self.paragraph_occurrences += 1
        sentence_key = tuple(normalize_text(sentence) for sentence in sentences)
        variant_key = (normalized_title, sentence_key)
        document = self.documents.get(digest)
        is_new_content = document is None
        if document is None:
            document = {
                "doc_id": digest, "content_hash": digest, "title": title, "text": text,
                "source": SOURCE_URL, "source_revision": self.revision, "source_split": "train",
                "source_variants": [],
            }
            self.documents[digest] = document
        else:
            if normalized_title in self._title_hashes:
                if digest in self._title_hashes[normalized_title]:
                    self.duplicates_by_title += 1
                else:
                    self.duplicates_by_hash += 1
            else:
                self.duplicates_by_hash += 1
        if variant_key not in self._variants[digest]:
            self._variants[digest].add(variant_key)
            document["source_variants"].append({"title": title, "sentences": list(sentences)})
        self._title_hashes[normalized_title].add(digest)
        self._title_labels.setdefault(normalized_title, title)
        return is_new_content

    def jsonl_sha256(self) -> str:
        """Hash the deterministic JSONL serialization without writing the large file."""
        digest = hashlib.sha256()
        for document in self.documents.values():
            line = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            digest.update((line + "\n").encode("utf-8"))
        return digest.hexdigest()

    def stats(self) -> dict[str, Any]:
        """Return content counts, collision examples, and paragraph size summaries."""
        lengths = [len(doc["text"]) for doc in self.documents.values()]
        collisions = sorted(
            title for title, hashes in self._title_hashes.items() if len(hashes) > 1
        )
        token_estimates = [math.ceil(length / 4) for length in lengths]
        return {
            "unique_content_documents": len(self.documents),
            "paragraph_occurrences": self.paragraph_occurrences,
            "duplicates_skipped_by_title": self.duplicates_by_title,
            "duplicates_skipped_by_hash": self.duplicates_by_hash,
            "empty_paragraphs_skipped": self.empty_paragraphs,
            "title_collision_count": len(collisions),
            "title_collision_examples": [{
                "title": self._title_labels[title],
                "version_count": len(self._title_hashes[title]),
                "content_hashes_sample": sorted(self._title_hashes[title])[:3],
            } for title in collisions[:3]],
            "paragraph_length_chars": {
                "average": round(mean(lengths), 2) if lengths else 0,
                "median": median(lengths) if lengths else 0,
            },
            "estimated_tokens_chars_div_4": {
                "average": round(mean(token_estimates), 2) if token_estimates else 0,
                "median": median(token_estimates) if token_estimates else 0,
            },
        }

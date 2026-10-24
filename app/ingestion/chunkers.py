"""Paragraph-level chunking for the first ingestion strategy."""

from __future__ import annotations

import re


PARAGRAPH_STRATEGY = "paragraph"
_PARAGRAPH_SEPARATOR = re.compile(r"\n\s*\n")


def paragraph_chunks(text: str) -> list[str]:
    """Split on blank lines while preserving each paragraph's original text."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    chunks = [part for part in _PARAGRAPH_SEPARATOR.split(text) if part.strip()]
    if not chunks:
        raise ValueError("text must contain at least one non-empty paragraph")
    return chunks

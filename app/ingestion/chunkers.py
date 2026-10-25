"""Paragraph-level chunking for the first ingestion strategy."""

from __future__ import annotations

import re


PARAGRAPH_STRATEGY = "paragraph"
FIXED_OVERLAP_STRATEGY = "fixed_overlap"
DEFAULT_FIXED_CHUNK_CHARS = 1_000
DEFAULT_FIXED_OVERLAP_CHARS = 150
_PARAGRAPH_SEPARATOR = re.compile(r"\n\s*\n")


def paragraph_chunks(text: str) -> list[str]:
    """Split on blank lines while preserving each paragraph's original text."""
    return [text[start:end] for start, end in paragraph_chunk_spans(text)]


def paragraph_chunk_spans(
    text: str, *, max_chunk_chars: int | None = None,
) -> list[tuple[int, int]]:
    """Return paragraph offsets, optionally splitting oversized paragraphs.

    The default keeps historical corpus chunking unchanged. Managed uploads can
    set a bound so one pathological paragraph cannot become a huge embedding
    input; offsets always remain Python Unicode character offsets.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if max_chunk_chars is not None and (type(max_chunk_chars) is not int or max_chunk_chars < 1):
        raise ValueError("max_chunk_chars must be a positive integer")
    spans = []
    start = 0
    for separator in _PARAGRAPH_SEPARATOR.finditer(text):
        if text[start:separator.start()].strip():
            _append_paragraph_spans(
                spans, start, separator.start(), max_chunk_chars=max_chunk_chars,
            )
        start = separator.end()
    if text[start:].strip():
        _append_paragraph_spans(spans, start, len(text), max_chunk_chars=max_chunk_chars)
    if not spans:
        raise ValueError("text must contain at least one non-empty paragraph")
    return spans


def _append_paragraph_spans(
    spans: list[tuple[int, int]],
    start: int,
    end: int,
    *,
    max_chunk_chars: int | None,
) -> None:
    if max_chunk_chars is None or end - start <= max_chunk_chars:
        spans.append((start, end))
        return
    for chunk_start in range(start, end, max_chunk_chars):
        spans.append((chunk_start, min(chunk_start + max_chunk_chars, end)))


def fixed_overlap_chunk_spans(
    text: str,
    *,
    chunk_size: int = DEFAULT_FIXED_CHUNK_CHARS,
    overlap: int = DEFAULT_FIXED_OVERLAP_CHARS,
) -> list[tuple[int, int]]:
    """Split into fixed character windows with deterministic overlapping offsets."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if type(chunk_size) is not int or chunk_size < 1:
        raise ValueError("chunk_size must be a positive integer")
    if type(overlap) is not int or not 0 <= overlap < chunk_size:
        raise ValueError("overlap must be a non-negative integer smaller than chunk_size")
    if not text.strip():
        raise ValueError("text must contain non-empty content")

    spans = []
    step = chunk_size - overlap
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if text[start:end].strip():
            spans.append((start, end))
        if end == len(text):
            break
        start += step
    return spans


def chunk_spans(
    text: str,
    strategy: str,
    *,
    chunk_size: int = DEFAULT_FIXED_CHUNK_CHARS,
    overlap: int = DEFAULT_FIXED_OVERLAP_CHARS,
    max_paragraph_chars: int | None = None,
) -> list[tuple[int, int]]:
    """Return validated offsets for one supported strategy."""
    if strategy == PARAGRAPH_STRATEGY:
        return paragraph_chunk_spans(text, max_chunk_chars=max_paragraph_chars)
    if strategy == FIXED_OVERLAP_STRATEGY:
        return fixed_overlap_chunk_spans(text, chunk_size=chunk_size, overlap=overlap)
    raise ValueError(f"unsupported chunking strategy: {strategy}")

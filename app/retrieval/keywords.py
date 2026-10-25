"""Query-term helpers for PostgreSQL full-text retrieval."""

from __future__ import annotations

import re
from typing import Literal


KeywordStrategy = Literal["or", "informative"]
DEFAULT_COMMON_TERM_THRESHOLD = 0.05

_QUERY_TOKEN = re.compile(
    r"(?:[^\W\d_](?:\.[^\W\d_]){1,}\.?)|"
    r"[\w]+(?:['’][\w]+)*(?:-[\w]+)*",
    flags=re.UNICODE,
)


def protected_query_text(query: str) -> str:
    """Keep original-case words and numeric identifiers out of common-term filtering.

    PostgreSQL later applies the same English stemming and stopword rules used
    for indexed chunks. Lowercase terms are not removed here; only lexemes whose
    analyzed corpus frequency crosses the configured cutoff may be filtered.
    """
    if not isinstance(query, str):
        raise ValueError("search query must be a string")
    protected = []
    seen: set[str] = set()
    for token in _QUERY_TOKEN.findall(query):
        if (
            any(character.isupper() or character.isdigit() for character in token)
            and token.casefold() not in seen
        ):
            protected.append(token)
            seen.add(token.casefold())
    return " ".join(protected)

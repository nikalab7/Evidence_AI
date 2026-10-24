"""Validate model-reported contradiction groups against verified claims."""

from collections.abc import Iterable
from typing import Any


def verified_conflict_groups(groups: Any, verified_claim_ids: Iterable[str]) -> list[list[str]]:
    """Keep only distinct groups with at least two claims that passed citation checks."""
    if not isinstance(groups, list):
        return []
    valid = set(verified_claim_ids)
    result: list[list[str]] = []
    for group in groups:
        if not isinstance(group, list) or any(not isinstance(item, str) for item in group):
            continue
        members = list(dict.fromkeys(group))
        if len(members) >= 2 and set(members) <= valid:
            result.append(members)
    return result

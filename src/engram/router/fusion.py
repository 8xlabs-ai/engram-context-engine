"""Reciprocal Rank Fusion (RRF) with k=60.

RRF combines N ranked lists into a single ordering. For each item, score =
sum over lists of 1 / (k + rank). Higher = better. k=60 is the standard,
untuned constant from the original paper; it is score-scale agnostic which
is why we don't need to calibrate per-source scoring.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

Item = TypeVar("Item", bound=Hashable)

DEFAULT_K = 60
DEFAULT_LIMIT = 20


@dataclass(frozen=True)
class FusedItem:
    item: Any
    score: float
    ranks_by_source: dict[str, int]


def rrf_fuse(
    ranked_lists: Mapping[str, Iterable[Item]],
    *,
    k: int = DEFAULT_K,
    limit: int = DEFAULT_LIMIT,
) -> list[FusedItem]:
    """Combine multiple ranked lists with RRF.

    `ranked_lists` maps a source name → iterable of items ordered best-first.
    Items must be hashable so they can be joined across lists.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if limit <= 0:
        raise ValueError("limit must be positive")

    scores: dict[Item, float] = {}
    ranks: dict[Item, dict[str, int]] = {}
    for source, items in ranked_lists.items():
        for rank_zero_based, item in enumerate(items):
            rank = rank_zero_based + 1  # RRF is 1-indexed
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
            ranks.setdefault(item, {})[source] = rank

    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], _tiebreak(kv[0])))
    return [
        FusedItem(item=item, score=score, ranks_by_source=dict(ranks[item]))
        for item, score in ordered[:limit]
    ]


def _tiebreak(item: Any) -> Any:
    """Stable tiebreak when two items have the same RRF score."""
    return repr(item)

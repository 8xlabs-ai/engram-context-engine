"""Router path classifier.

Given a query envelope, pick path A (discovery-first), B (precision-first),
or C (fusion). See docs 06 §3 and the `retrieval-router` spec.
"""

from __future__ import annotations

from typing import Any, Literal

Path = Literal["A", "B", "C"]


def classify_query(args: dict[str, Any]) -> Path:
    """Pick the retrieval path for a given router input envelope.

    - B when name_path is supplied and no free text query.
    - A when only a free-text query is supplied (no name_path).
    - C when both are supplied, or when the caller is an engram.* composed
      tool that explicitly requests fusion (via `fusion=True`).
    """
    name_path = _str(args, "name_path")
    query = _str(args, "query") or _str(args, "free_query")
    fusion = bool(args.get("fusion"))

    if fusion:
        return "C"
    if name_path and query:
        return "C"
    if name_path:
        return "B"
    return "A"


def _str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    return value if isinstance(value, str) and value.strip() else ""

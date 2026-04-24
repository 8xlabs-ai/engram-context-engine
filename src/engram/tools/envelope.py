from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any

from engram import __version__

PROTOCOL_VERSION = "v1"


def success(result: Any, meta_extra: dict[str, Any] | None = None) -> dict[str, Any]:
    meta: dict[str, Any] = {"protocol_version": PROTOCOL_VERSION}
    if meta_extra:
        meta.update(meta_extra)
    return {"result": result, "meta": meta}


def failure(
    code: str,
    message: str,
    details: Any | None = None,
    meta_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {"protocol_version": PROTOCOL_VERSION, "error": code}
    if meta_extra:
        meta.update(meta_extra)
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error, "meta": meta}


def engram_version() -> str:
    return __version__


@contextmanager
def latency_meter() -> Any:
    """Usage: with latency_meter() as m: ... ; m['latency_ms']."""
    holder: dict[str, float] = {"latency_ms": 0.0}
    start = time.perf_counter()
    try:
        yield holder
    finally:
        holder["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)


STABLE_ERROR_CODES = frozenset(
    {
        "symbol-not-found",
        "drawer-not-found",
        "upstream-unavailable",
        "timeout",
        "invalid-input",
        "fact-checker-unavailable",
        "all-sources-unavailable",
        "consistency-state-hint",
    }
)

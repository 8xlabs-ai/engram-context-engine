from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from engram import __version__
from engram.link.store import (
    get_symbol,
    history_for,
    init_db,
    memory_anchors_for_symbol,
    open_db,
    upsert_anchor_memory_chunk,
    upsert_anchor_symbol_memory,
    upsert_symbol,
)
from engram.tools.envelope import failure, latency_meter, success
from engram.tools.registry import ToolRegistry, ToolSpec
from engram.upstream.client import UpstreamClient
from engram.upstream.supervisor import Supervisor

log = logging.getLogger("engram.tools")

HEALTH_DESCRIPTION = (
    "Report Engram and upstream liveness plus anchor-store counts.\n"
    "Use when you need a one-shot status probe before making a compound call."
)

ANCHOR_MEMORY_TO_SYMBOL_DESCRIPTION = (
    "Anchor a MemPalace drawer to a code symbol so future queries tie them together.\n"
    "Prefer this over writing anchor SQL directly; duplicate calls are idempotent."
)

ANCHOR_MEMORY_TO_CHUNK_DESCRIPTION = (
    "Anchor a MemPalace drawer to a specific code range (file + line span).\n"
    "Use when the memory is about a range rather than a whole symbol (e.g., review comments)."
)

SYMBOL_HISTORY_DESCRIPTION = (
    "Return a symbol's identity history (creations, renames, moves, tombstones).\n"
    "Use when debugging anchor staleness or answering 'what used to be here?'."
)

# Lightweight probes per upstream — each is a tool on the upstream that returns
# fast and does not mutate state. Picked from docs 01–03.
PROBE_TOOL = {
    "serena": "get_current_config",
    "mempalace": "mempalace_status",
    "claude_context": "get_indexing_status",
}


DrawerLookup = Callable[[str], Awaitable[dict[str, Any] | None]]
SymbolLookup = Callable[[str, str], Awaitable[dict[str, Any] | None]]


def register_engram_tools(
    registry: ToolRegistry,
    anchor_db_path: Path,
    supervisor: Supervisor | None = None,
    drawer_lookup: DrawerLookup | None = None,
    symbol_lookup: SymbolLookup | None = None,
) -> None:
    """Register all engram.* tools.

    `drawer_lookup` and `symbol_lookup` are override hooks used by tests; in
    production the closures derived from `supervisor` are used.
    """
    drawer_lookup = drawer_lookup or _default_drawer_lookup(supervisor)
    symbol_lookup = symbol_lookup or _default_symbol_lookup(supervisor)

    _register_health(registry, anchor_db_path, supervisor)
    _register_anchor_memory_to_symbol(
        registry, anchor_db_path, drawer_lookup, symbol_lookup
    )
    _register_anchor_memory_to_chunk(registry, anchor_db_path, drawer_lookup)
    _register_symbol_history(registry, anchor_db_path, drawer_lookup)


# -----------------------------------------------------------------------------
# engram.health
# -----------------------------------------------------------------------------


def _register_health(
    registry: ToolRegistry, anchor_db_path: Path, supervisor: Supervisor | None
) -> None:
    async def health_handler(_args: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            upstreams = await _probe_all(supervisor)
            status = _roll_up_status(upstreams)
            result: dict[str, Any] = {
                "status": status,
                "engram_version": __version__,
                "upstreams": upstreams,
                "anchor_store": _anchor_counts(anchor_db_path),
            }
        return success(result, meta_extra={"latency_ms": m["latency_ms"]})

    registry.register(
        ToolSpec(
            name="engram.health",
            description=HEALTH_DESCRIPTION,
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=health_handler,
        )
    )


# -----------------------------------------------------------------------------
# engram.anchor_memory_to_symbol
# -----------------------------------------------------------------------------


def _register_anchor_memory_to_symbol(
    registry: ToolRegistry,
    anchor_db_path: Path,
    drawer_lookup: DrawerLookup,
    symbol_lookup: SymbolLookup,
) -> None:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            drawer_id = args.get("drawer_id")
            name_path = args.get("name_path")
            relative_path = args.get("relative_path")
            confidence = float(args.get("confidence", 1.0))
            if not all(isinstance(x, str) and x for x in (drawer_id, name_path, relative_path)):
                return failure(
                    "invalid-input",
                    "drawer_id, name_path, and relative_path are required",
                    meta_extra={"latency_ms": m["latency_ms"]},
                )

            drawer = await drawer_lookup(drawer_id)
            if drawer is None:
                return failure(
                    "drawer-not-found",
                    f"drawer_id not found in MemPalace: {drawer_id}",
                    meta_extra={"latency_ms": m["latency_ms"]},
                )

            symbol = await symbol_lookup(name_path, relative_path)

            conn = _connect_or_init(anchor_db_path)
            try:
                kind = int(symbol.get("kind", 0)) if symbol else 0
                symbol_id = upsert_symbol(
                    conn,
                    name_path=name_path,
                    relative_path=relative_path,
                    kind=kind,
                )
                anchor_id = upsert_anchor_symbol_memory(
                    conn,
                    symbol_id=symbol_id,
                    drawer_id=drawer_id,
                    wing=str(drawer.get("wing", "")),
                    room=str(drawer.get("room", "")),
                    created_by="explicit",
                    confidence=confidence,
                )
            finally:
                conn.close()

        return success(
            {"anchor_id": anchor_id, "symbol_id": symbol_id},
            meta_extra={
                "latency_ms": m["latency_ms"],
                "symbol_resolved_via_upstream": symbol is not None,
            },
        )

    registry.register(
        ToolSpec(
            name="engram.anchor_memory_to_symbol",
            description=ANCHOR_MEMORY_TO_SYMBOL_DESCRIPTION,
            input_schema={
                "type": "object",
                "properties": {
                    "drawer_id": {"type": "string"},
                    "name_path": {"type": "string"},
                    "relative_path": {"type": "string"},
                    "confidence": {"type": "number", "default": 1.0},
                },
                "required": ["drawer_id", "name_path", "relative_path"],
                "additionalProperties": False,
            },
            handler=handler,
        )
    )


# -----------------------------------------------------------------------------
# engram.anchor_memory_to_chunk
# -----------------------------------------------------------------------------


def _register_anchor_memory_to_chunk(
    registry: ToolRegistry,
    anchor_db_path: Path,
    drawer_lookup: DrawerLookup,
) -> None:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            drawer_id = args.get("drawer_id")
            relative_path = args.get("relative_path")
            start_line = args.get("start_line")
            end_line = args.get("end_line")
            language = args.get("language", "unknown")
            if not isinstance(drawer_id, str) or not drawer_id:
                return failure(
                    "invalid-input", "drawer_id required",
                    meta_extra={"latency_ms": m["latency_ms"]},
                )
            if not isinstance(relative_path, str) or not relative_path:
                return failure(
                    "invalid-input", "relative_path required",
                    meta_extra={"latency_ms": m["latency_ms"]},
                )
            if not isinstance(start_line, int) or not isinstance(end_line, int):
                return failure(
                    "invalid-input", "start_line and end_line must be integers",
                    meta_extra={"latency_ms": m["latency_ms"]},
                )
            drawer = await drawer_lookup(drawer_id)
            if drawer is None:
                return failure(
                    "drawer-not-found",
                    f"drawer_id not found: {drawer_id}",
                    meta_extra={"latency_ms": m["latency_ms"]},
                )
            conn = _connect_or_init(anchor_db_path)
            try:
                anchor_id = upsert_anchor_memory_chunk(
                    conn,
                    drawer_id=drawer_id,
                    relative_path=relative_path,
                    start_line=int(start_line),
                    end_line=int(end_line),
                    language=str(language),
                    index_generation=0,
                )
            finally:
                conn.close()
        return success(
            {"anchor_id": anchor_id},
            meta_extra={"latency_ms": m["latency_ms"]},
        )

    registry.register(
        ToolSpec(
            name="engram.anchor_memory_to_chunk",
            description=ANCHOR_MEMORY_TO_CHUNK_DESCRIPTION,
            input_schema={
                "type": "object",
                "properties": {
                    "drawer_id": {"type": "string"},
                    "relative_path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                    "language": {"type": "string"},
                },
                "required": ["drawer_id", "relative_path", "start_line", "end_line"],
                "additionalProperties": False,
            },
            handler=handler,
        )
    )


# -----------------------------------------------------------------------------
# engram.symbol_history
# -----------------------------------------------------------------------------


def _register_symbol_history(
    registry: ToolRegistry,
    anchor_db_path: Path,
    drawer_lookup: DrawerLookup,
) -> None:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            name_path = args.get("name_path")
            relative_path = args.get("relative_path")
            include_memories = bool(args.get("include_memories", False))
            if not isinstance(name_path, str) or not name_path:
                return failure(
                    "invalid-input",
                    "name_path required",
                    meta_extra={"latency_ms": m["latency_ms"]},
                )
            conn = _connect_or_init(anchor_db_path)
            try:
                row = (
                    get_symbol(conn, name_path, relative_path)
                    if isinstance(relative_path, str) and relative_path
                    else None
                )
                if row is None:
                    return failure(
                        "symbol-not-found",
                        f"no live symbol matches {name_path}@{relative_path}",
                        meta_extra={"latency_ms": m["latency_ms"]},
                    )
                history = [h.__dict__ for h in history_for(conn, row.symbol_id)]
                result: dict[str, Any] = {
                    "symbol_id": row.symbol_id,
                    "name_path": row.name_path,
                    "relative_path": row.relative_path,
                    "history": history,
                }
                if include_memories:
                    anchors = memory_anchors_for_symbol(conn, row.symbol_id)
                    memories: list[dict[str, Any]] = []
                    for a in anchors:
                        drawer = await drawer_lookup(str(a["drawer_id"]))
                        memories.append(
                            {
                                "drawer_id": a["drawer_id"],
                                "confidence": a["confidence"],
                                "wing": a["wing"],
                                "room": a["room"],
                                "drawer": drawer,
                            }
                        )
                    result["memories"] = memories
            finally:
                conn.close()
        return success(result, meta_extra={"latency_ms": m["latency_ms"]})

    registry.register(
        ToolSpec(
            name="engram.symbol_history",
            description=SYMBOL_HISTORY_DESCRIPTION,
            input_schema={
                "type": "object",
                "properties": {
                    "name_path": {"type": "string"},
                    "relative_path": {"type": "string"},
                    "include_memories": {"type": "boolean", "default": False},
                },
                "required": ["name_path"],
                "additionalProperties": False,
            },
            handler=handler,
        )
    )


# -----------------------------------------------------------------------------
# default lookup closures (production wiring)
# -----------------------------------------------------------------------------


def _default_drawer_lookup(supervisor: Supervisor | None) -> DrawerLookup:
    async def lookup(drawer_id: str) -> dict[str, Any] | None:
        if supervisor is None:
            return None
        client = supervisor.get("mempalace")
        if client is None:
            return None
        try:
            result = await client.call_tool(
                "mempalace_get_drawer", {"drawer_id": drawer_id}
            )
        except Exception:  # noqa: BLE001
            return None
        if result.isError:
            return None
        return _as_structured(result)

    return lookup


def _default_symbol_lookup(supervisor: Supervisor | None) -> SymbolLookup:
    async def lookup(name_path: str, relative_path: str) -> dict[str, Any] | None:
        if supervisor is None:
            return None
        client = supervisor.get("serena")
        if client is None:
            return None
        try:
            result = await client.call_tool(
                "find_symbol",
                {"name_path": name_path, "relative_path": relative_path},
            )
        except Exception:  # noqa: BLE001
            return None
        if result.isError:
            return None
        return _as_structured(result)

    return lookup


def _as_structured(result: Any) -> dict[str, Any] | None:
    if getattr(result, "structuredContent", None):
        return dict(result.structuredContent)
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is None:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _connect_or_init(path: Path):
    if path.exists():
        return open_db(path)
    return init_db(path)


# -----------------------------------------------------------------------------
# health probes
# -----------------------------------------------------------------------------


async def _probe_all(supervisor: Supervisor | None) -> dict[str, dict[str, Any]]:
    upstreams: dict[str, dict[str, Any]] = {
        name: {"ok": False, "reason": "not connected"} for name in PROBE_TOOL
    }
    if supervisor is None:
        return upstreams
    for name, probe in PROBE_TOOL.items():
        client = supervisor.get(name)
        if client is None:
            continue
        upstreams[name] = await _probe_one(client, probe)
    return upstreams


async def _probe_one(client: UpstreamClient, probe_tool: str) -> dict[str, Any]:
    has_tool = any(t.name == probe_tool for t in client.tools)
    if not has_tool:
        return {"ok": True, "latency_ms": 0.0, "probe": None}
    start = time.perf_counter()
    try:
        result = await client.call_tool(probe_tool, {})
    except Exception as exc:  # noqa: BLE001
        log.warning("probe %s on %s failed: %s", probe_tool, client.spec.name, exc)
        return {"ok": False, "reason": str(exc), "probe": probe_tool}
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    if result.isError:
        return {"ok": False, "reason": "probe returned error", "probe": probe_tool}
    return {"ok": True, "latency_ms": latency_ms, "probe": probe_tool}


def _roll_up_status(upstreams: dict[str, dict[str, Any]]) -> str:
    oks = [u["ok"] for u in upstreams.values()]
    if all(oks):
        return "ok"
    if any(oks):
        return "degraded"
    return "down"


def _anchor_counts(db_path: Path) -> dict[str, int]:
    if not db_path.exists():
        return {"symbols": 0, "anchors_symbol_memory": 0, "anchors_symbol_chunk": 0}
    conn = open_db(db_path)
    try:
        return {
            "symbols": _count(conn, "symbols"),
            "anchors_symbol_memory": _count(conn, "anchors_symbol_memory"),
            "anchors_symbol_chunk": _count(conn, "anchors_symbol_chunk"),
        }
    finally:
        conn.close()


def _count(conn: Any, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

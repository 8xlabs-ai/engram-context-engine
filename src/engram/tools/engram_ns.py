from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from engram import __version__
from engram.events import HookBus
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
from engram.router.cache import LRUCache
from engram.router.classifier import classify_query
from engram.router.dispatcher import RouterDispatcher
from engram.tools.contradicts import register_contradicts
from engram.tools.envelope import failure, latency_meter, success
from engram.tools.notify import register_notify_tools
from engram.tools.registry import ToolRegistry, ToolSpec
from engram.upstream.client import UpstreamClient
from engram.upstream.supervisor import Supervisor
from engram.workers.reconciler import reconcile as run_reconcile
from engram.workers.wal_tailer import wal_lag_seconds

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

WHY_DESCRIPTION = (
    "Explain why a symbol exists: resolve it, list anchored / relevant memories, and KG facts.\n"
    "Prefer this over code.find_symbol when the question is *why*, not *where*."
)

WHERE_DECISION_DESCRIPTION = (
    "Find every place a KG-recorded decision is implemented in the code.\n"
    "Use when you have a decision entity and need to see what code honors it."
)

RECONCILE_DESCRIPTION = (
    "Sweep the anchor store to repair stale rows (dead drawers, tombstoned symbols).\n"
    "Use when engram.health reports a large anchor_store age or after a manual cleanup."
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
MemSearch = Callable[[str], Awaitable[list[dict[str, Any]]]]
KgQuery = Callable[[str], Awaitable[list[dict[str, Any]]]]
VecSearch = Callable[[str, int], Awaitable[list[dict[str, Any]]]]
ChunkSymbolResolver = Callable[
    [dict[str, Any]], Awaitable[dict[str, Any] | None]
]


def register_engram_tools(
    registry: ToolRegistry,
    anchor_db_path: Path,
    supervisor: Supervisor | None = None,
    drawer_lookup: DrawerLookup | None = None,
    symbol_lookup: SymbolLookup | None = None,
    mem_search: MemSearch | None = None,
    kg_query: KgQuery | None = None,
    vec_search: VecSearch | None = None,
    chunk_symbol_resolver: ChunkSymbolResolver | None = None,
    bus: HookBus | None = None,
    cache: LRUCache | None = None,
) -> None:
    """Register all engram.* tools.

    `drawer_lookup`, `symbol_lookup`, `mem_search`, `kg_query`, and `vec_search`
    are override hooks used by tests; in production the closures derived from
    `supervisor` are used. `bus` enables notify tools that publish into the
    HookBus; if absent, those tools are not registered. `cache`, when supplied,
    short-circuits `engram.why` on warm queries; eviction is wired separately
    via `LRUCache.subscribe_to(bus)`.
    """
    workspace_root = anchor_db_path.parent.parent
    drawer_lookup = drawer_lookup or _default_drawer_lookup(supervisor)
    symbol_lookup = symbol_lookup or _default_symbol_lookup(supervisor)
    mem_search = mem_search or _default_mem_search(supervisor)
    kg_query = kg_query or _default_kg_query(supervisor)
    vec_search = vec_search or _default_vec_search(supervisor, workspace_root)
    chunk_symbol_resolver = chunk_symbol_resolver or _default_chunk_symbol_resolver(
        supervisor, anchor_db_path
    )

    _register_health(registry, anchor_db_path, supervisor)
    _register_anchor_memory_to_symbol(
        registry, anchor_db_path, drawer_lookup, symbol_lookup
    )
    _register_anchor_memory_to_chunk(registry, anchor_db_path, drawer_lookup)
    _register_symbol_history(registry, anchor_db_path, drawer_lookup)
    _register_why(
        registry,
        anchor_db_path,
        symbol_lookup=symbol_lookup,
        mem_search=mem_search,
        kg_query=kg_query,
        vec_search=vec_search,
        cache=cache,
    )
    _register_where_does_decision_apply(
        registry,
        kg_query=kg_query,
        vec_search=vec_search,
        chunk_symbol_resolver=chunk_symbol_resolver,
    )
    _register_reconcile(registry, anchor_db_path, drawer_lookup)
    register_contradicts(registry)
    if bus is not None:
        register_notify_tools(registry, anchor_db_path, bus)


# -----------------------------------------------------------------------------
# engram.health
# -----------------------------------------------------------------------------


def _register_health(
    registry: ToolRegistry, anchor_db_path: Path, supervisor: Supervisor | None
) -> None:
    # anchor_db_path is .engram/anchors.sqlite under the workspace root.
    workspace_root = anchor_db_path.parent.parent

    async def health_handler(_args: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            upstreams = await _probe_all(supervisor, workspace_root)
            lag = wal_lag_seconds(anchor_db_path)
            if lag is not None and "mempalace" in upstreams:
                upstreams["mempalace"]["wal_lag_seconds"] = lag
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
# engram.why
# -----------------------------------------------------------------------------


def _register_why(
    registry: ToolRegistry,
    anchor_db_path: Path,
    *,
    symbol_lookup: SymbolLookup,
    mem_search: MemSearch,
    kg_query: KgQuery,
    vec_search: VecSearch,
    cache: LRUCache | None = None,
) -> None:
    dispatcher = RouterDispatcher(
        vec_search=vec_search,
        mem_search=mem_search,
        kg_query=kg_query,
        symbol_lookup=symbol_lookup,
    )

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            name_path = args.get("name_path")
            relative_path = args.get("relative_path")
            free_query = args.get("free_query")

            if not (isinstance(name_path, str) and name_path) and not (
                isinstance(free_query, str) and free_query
            ):
                return failure(
                    "invalid-input",
                    "at least one of name_path or free_query is required",
                    meta_extra={"latency_ms": m["latency_ms"]},
                )

            # Preserve the symbol-not-found contract: when both name_path and
            # relative_path are supplied, an unresolved symbol is a hard
            # failure rather than a partial result.
            if (
                isinstance(name_path, str)
                and name_path
                and isinstance(relative_path, str)
                and relative_path
            ):
                sym = await symbol_lookup(name_path, relative_path)
                if sym is None:
                    path = classify_query(
                        {"name_path": name_path, "query": free_query}
                    )
                    return failure(
                        "symbol-not-found",
                        f"no symbol resolved for {name_path}@{relative_path}",
                        meta_extra={
                            "latency_ms": m["latency_ms"],
                            "path_used": path,
                        },
                    )

            cache_key_args = {
                "name_path": name_path,
                "relative_path": relative_path,
                "free_query": free_query,
            }
            cached = cache.get("engram.why", cache_key_args) if cache else None
            if cached is not None:
                router_result = cached
            else:
                router_result = await dispatcher.dispatch(
                    {
                        "name_path": name_path,
                        "relative_path": relative_path,
                        "query": free_query,
                    }
                )
                if cache is not None:
                    cache.put("engram.why", cache_key_args, router_result)

        result = {
            "symbol": router_result.symbol,
            "memories": router_result.memories,
            "facts": router_result.facts,
            "chunks": router_result.chunks,
            "fused": router_result.fused,
        }
        meta_extra = {
            "latency_ms": m["latency_ms"],
            "path_used": router_result.path_used,
            "sources_used": router_result.sources_used,
        }
        if router_result.warnings:
            meta_extra["warnings"] = router_result.warnings
        return success(result, meta_extra=meta_extra)

    registry.register(
        ToolSpec(
            name="engram.why",
            description=WHY_DESCRIPTION,
            input_schema={
                "type": "object",
                "properties": {
                    "name_path": {"type": "string"},
                    "relative_path": {"type": "string"},
                    "free_query": {"type": "string"},
                },
                "additionalProperties": False,
            },
            handler=handler,
        )
    )


# -----------------------------------------------------------------------------
# engram.reconcile
# -----------------------------------------------------------------------------


def _register_reconcile(
    registry: ToolRegistry, anchor_db_path: Path, drawer_lookup: DrawerLookup
) -> None:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            scope = str(args.get("scope", "all"))
            dry_run = bool(args.get("dry_run", False))
            if scope not in ("symbols", "chunks", "memories", "all"):
                return failure(
                    "invalid-input",
                    f"scope must be one of symbols/chunks/memories/all, got {scope!r}",
                    meta_extra={"latency_ms": m["latency_ms"]},
                )
            report = await run_reconcile(
                anchor_db_path,
                scope=scope,
                dry_run=dry_run,
                drawer_lookup=drawer_lookup,
            )
        return success(
            {
                "scope": scope,
                "dry_run": dry_run,
                "changed": report.changed,
                "scanned": report.scanned,
                "warnings": report.warnings,
            },
            meta_extra={"latency_ms": m["latency_ms"]},
        )

    registry.register(
        ToolSpec(
            name="engram.reconcile",
            description=RECONCILE_DESCRIPTION,
            input_schema={
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["symbols", "chunks", "memories", "all"],
                    },
                    "dry_run": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
            handler=handler,
        )
    )


# -----------------------------------------------------------------------------
# engram.where_does_decision_apply
# -----------------------------------------------------------------------------


def _register_where_does_decision_apply(
    registry: ToolRegistry,
    *,
    kg_query: KgQuery,
    vec_search: VecSearch,
    chunk_symbol_resolver: ChunkSymbolResolver,
) -> None:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            entity = args.get("decision_entity")
            limit = int(args.get("limit", 10))
            if not isinstance(entity, str) or not entity:
                return failure(
                    "invalid-input",
                    "decision_entity is required",
                    meta_extra={"latency_ms": m["latency_ms"]},
                )

            facts = await kg_query(entity)
            implementations: list[dict[str, Any]] = []
            seen: set[str] = set()

            # Use facts as hints: for each (subject, predicate, object) triple,
            # the `object` is a likely related entity worth vec.searching.
            related = _related_terms(entity, facts)
            for term in related[:limit]:
                chunks = await vec_search(term, limit)
                for chunk in chunks:
                    rel = chunk.get("relativePath") or chunk.get("relative_path")
                    start = chunk.get("startLine") or chunk.get("start_line")
                    if not isinstance(rel, str) or not isinstance(start, int):
                        continue
                    sig = f"{rel}:{start}"
                    if sig in seen:
                        continue
                    seen.add(sig)
                    enc = chunk.get("enclosing_symbol")
                    if enc is None:
                        # Resolve from the chunk's line range, NOT from the
                        # decision-entity term — Serena would never recognize
                        # `gdpr_retention_30d` as a name_path.
                        enc = await chunk_symbol_resolver(chunk)
                    implementations.append({"chunk": chunk, "symbol": enc})
                    if len(implementations) >= limit:
                        break
                if len(implementations) >= limit:
                    break

        return success(
            {
                "entity": entity,
                "facts": facts,
                "implementations": implementations,
            },
            meta_extra={"latency_ms": m["latency_ms"], "path_used": "C"},
        )

    registry.register(
        ToolSpec(
            name="engram.where_does_decision_apply",
            description=WHERE_DECISION_DESCRIPTION,
            input_schema={
                "type": "object",
                "properties": {
                    "decision_entity": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["decision_entity"],
                "additionalProperties": False,
            },
            handler=handler,
        )
    )


def _related_terms(entity: str, facts: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = [entity]
    seen: set[str] = {entity}
    for fact in facts:
        for key in ("object", "subject"):
            value = fact.get(key)
            if isinstance(value, str) and value and value not in seen:
                seen.add(value)
                terms.append(value)
    return terms


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


def _default_chunk_symbol_resolver(
    supervisor: Supervisor | None, anchor_db_path: Path
) -> ChunkSymbolResolver:
    from engram.tools.vec_enrich import resolve_chunk_symbol

    async def resolve(chunk: dict[str, Any]) -> dict[str, Any] | None:
        conn = open_db(anchor_db_path) if anchor_db_path.exists() else None
        client = supervisor.get("serena") if supervisor is not None else None
        try:
            return await resolve_chunk_symbol(conn, client, chunk)
        finally:
            if conn is not None:
                conn.close()

    return resolve


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


def _default_vec_search(
    supervisor: Supervisor | None, workspace_root: Path | None
) -> VecSearch:
    async def search(query: str, limit: int) -> list[dict[str, Any]]:
        if supervisor is None or workspace_root is None:
            return []
        client = supervisor.get("claude_context")
        if client is None:
            return []
        try:
            result = await client.call_tool(
                "search_code",
                {"path": str(workspace_root), "query": query, "limit": limit},
            )
        except Exception:  # noqa: BLE001
            return []
        if result.isError:
            return []
        payload = _as_structured(result)
        if isinstance(payload, list):
            return [p for p in payload if isinstance(p, dict)]
        if isinstance(payload, dict):
            results = payload.get("results") or payload.get("chunks")
            if isinstance(results, list):
                return [p for p in results if isinstance(p, dict)]
        return []

    return search


MEM_SEARCH_QUERY_MAX = 250  # MemPalace mempalace_search 'query' maxLength.
MEM_SEARCH_DEFAULT_LIMIT = 10  # router likes a few extra for fusion.


def _default_mem_search(supervisor: Supervisor | None) -> MemSearch:
    async def search(query: str) -> list[dict[str, Any]]:
        if supervisor is None:
            return []
        client = supervisor.get("mempalace")
        if client is None:
            return []
        keyword_query = _to_keyword_query(query)
        if not keyword_query:
            return []
        try:
            result = await client.call_tool(
                "mempalace_search",
                {"query": keyword_query, "limit": MEM_SEARCH_DEFAULT_LIMIT},
            )
        except Exception:  # noqa: BLE001
            return []
        if result.isError:
            return []
        payload = _as_structured(result)
        if isinstance(payload, list):
            return [p for p in payload if isinstance(p, dict)]
        if isinstance(payload, dict):
            results = payload.get("results") or payload.get("drawers")
            if isinstance(results, list):
                return [p for p in results if isinstance(p, dict)]
        return []

    return search


def _to_keyword_query(raw: str) -> str:
    """Normalize a router query for MemPalace's keyword-only 'query' field.

    - Replace `/` and `.` with spaces (turn `Pipeline/process_batch` into
      `Pipeline process_batch` — embeddings handle the rest).
    - Collapse whitespace.
    - Truncate to 250 characters (MemPalace cap).
    """
    if not raw:
        return ""
    cleaned = raw.replace("/", " ").replace(".", " ")
    cleaned = " ".join(cleaned.split())
    return cleaned[:MEM_SEARCH_QUERY_MAX]


def _default_kg_query(supervisor: Supervisor | None) -> KgQuery:
    async def query(subject: str) -> list[dict[str, Any]]:
        if supervisor is None:
            return []
        client = supervisor.get("mempalace")
        if client is None:
            return []
        try:
            result = await client.call_tool(
                "mempalace_kg_query", {"subject": subject}
            )
        except Exception:  # noqa: BLE001
            return []
        if result.isError:
            return []
        payload = _as_structured(result)
        if isinstance(payload, list):
            return [p for p in payload if isinstance(p, dict)]
        if isinstance(payload, dict):
            triples = payload.get("triples") or payload.get("facts")
            if isinstance(triples, list):
                return [p for p in triples if isinstance(p, dict)]
        return []

    return query


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


async def _probe_all(
    supervisor: Supervisor | None, workspace_root: Path | None = None
) -> dict[str, dict[str, Any]]:
    upstreams: dict[str, dict[str, Any]] = {
        name: {"ok": False, "reason": "not connected"} for name in PROBE_TOOL
    }
    if supervisor is None:
        return upstreams
    for name, probe in PROBE_TOOL.items():
        client = supervisor.get(name)
        if client is None:
            continue
        upstreams[name] = await _probe_one(client, probe, workspace_root)
    return upstreams


async def _probe_one(
    client: UpstreamClient, probe_tool: str, workspace_root: Path | None = None
) -> dict[str, Any]:
    has_tool = any(t.name == probe_tool for t in client.tools)
    if not has_tool:
        return {"ok": True, "latency_ms": 0.0, "probe": None}
    args = _probe_args(client.spec.name, workspace_root)
    start = time.perf_counter()
    try:
        result = await client.call_tool(probe_tool, args)
    except Exception as exc:  # noqa: BLE001
        log.warning("probe %s on %s failed: %s", probe_tool, client.spec.name, exc)
        return {"ok": False, "reason": str(exc), "probe": probe_tool}
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    if result.isError:
        return {"ok": False, "reason": "probe returned error", "probe": probe_tool}
    return {"ok": True, "latency_ms": latency_ms, "probe": probe_tool}


def _probe_args(upstream: str, workspace_root: Path | None) -> dict[str, Any]:
    # claude-context's get_indexing_status requires the codebase path; other
    # probes accept empty args.
    if upstream == "claude_context" and workspace_root is not None:
        return {"path": str(workspace_root)}
    return {}


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

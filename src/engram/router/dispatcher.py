"""Router dispatcher — Paths A, B, C.

Composes vec / mem / kg / symbol sources per `classify_query`. Path C fuses
multiple sources with RRF (doc 06 §2). Path A or B short-circuits when
fusion isn't needed.

Sources are injected as async callables at construction time so tests can
pass fakes and production can wire to the Supervisor.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from engram.router.classifier import Path, classify_query
from engram.router.fusion import FusedItem, rrf_fuse

VecSearch = Callable[[str, int], Awaitable[list[dict[str, Any]]]]
MemSearch = Callable[[str], Awaitable[list[dict[str, Any]]]]
KgQuery = Callable[[str], Awaitable[list[dict[str, Any]]]]
SymbolLookup = Callable[[str, str], Awaitable[dict[str, Any] | None]]


@dataclass
class RouterResult:
    path_used: Path
    symbol: dict[str, Any] | None = None
    memories: list[dict[str, Any]] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)
    chunks: list[dict[str, Any]] = field(default_factory=list)
    fused: list[dict[str, Any]] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class RouterDispatcher:
    vec_search: VecSearch
    mem_search: MemSearch
    kg_query: KgQuery
    symbol_lookup: SymbolLookup
    default_k: int = 20

    async def dispatch(self, args: dict[str, Any]) -> RouterResult:
        path = classify_query(args)
        if path == "A":
            return await self._path_a(args)
        if path == "B":
            return await self._path_b(args)
        return await self._path_c(args)

    async def _path_a(self, args: dict[str, Any]) -> RouterResult:
        query = str(args.get("query") or args.get("free_query") or "")
        result = RouterResult(path_used="A")
        if not query:
            return result
        chunks = await _safe_list(self.vec_search(query, self.default_k), result, "claude_context")
        result.chunks = chunks
        return result

    async def _path_b(self, args: dict[str, Any]) -> RouterResult:
        name_path = str(args.get("name_path") or "")
        relative_path = args.get("relative_path")
        result = RouterResult(path_used="B")
        if not name_path:
            return result

        if isinstance(relative_path, str) and relative_path:
            sym = await _safe_value(
                self.symbol_lookup(name_path, relative_path), result, "serena"
            )
            result.symbol = sym
        memories = await _safe_list(self.mem_search(name_path), result, "mempalace")
        facts = await _safe_list(self.kg_query(name_path), result, "mempalace")
        result.memories = memories
        result.facts = facts
        return result

    async def _path_c(self, args: dict[str, Any]) -> RouterResult:
        import asyncio

        result = RouterResult(path_used="C")
        name_path = str(args.get("name_path") or "")
        query = str(args.get("query") or args.get("free_query") or name_path)

        async def run_vec():
            result.chunks = await _safe_list(
                self.vec_search(query, self.default_k), result, "claude_context"
            )

        async def run_mem():
            result.memories = await _safe_list(
                self.mem_search(query), result, "mempalace"
            )

        async def run_kg():
            result.facts = await _safe_list(
                self.kg_query(name_path or query), result, "kg"
            )

        coros = [run_vec(), run_mem(), run_kg()]
        if name_path and isinstance(args.get("relative_path"), str):
            async def run_symbol():
                result.symbol = await _safe_value(
                    self.symbol_lookup(name_path, args["relative_path"]),
                    result,
                    "serena",
                )

            coros.append(run_symbol())

        await asyncio.gather(*coros, return_exceptions=False)

        # Build ranked lists keyed by stable identifiers for fusion.
        vec_ids = [_chunk_key(c) for c in result.chunks]
        mem_ids = [_memory_key(m) for m in result.memories]
        kg_ids = [_fact_key(f) for f in result.facts]

        lists: dict[str, list[str]] = {}
        if vec_ids:
            lists["vec"] = vec_ids
        if mem_ids:
            lists["mem"] = mem_ids
        if kg_ids:
            lists["kg"] = kg_ids

        if lists:
            fused: list[FusedItem] = rrf_fuse(lists, limit=self.default_k)
            result.fused = [
                {
                    "item_id": f.item,
                    "score": round(f.score, 6),
                    "ranks_by_source": f.ranks_by_source,
                }
                for f in fused
            ]
        return result


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _chunk_key(chunk: dict[str, Any]) -> str:
    return (
        f"chunk:{chunk.get('relative_path', '?')}"
        f":{chunk.get('start_line', 0)}-{chunk.get('end_line', 0)}"
    )


def _memory_key(mem: dict[str, Any]) -> str:
    return f"mem:{mem.get('drawer_id', '?')}"


def _fact_key(fact: dict[str, Any]) -> str:
    return (
        f"kg:{fact.get('subject', '?')}|{fact.get('predicate', '?')}"
        f"|{fact.get('object', '?')}"
    )


async def _safe_list(coro: Awaitable[Any], result: RouterResult, source: str) -> list[dict[str, Any]]:
    try:
        value = await coro
    except Exception as exc:  # noqa: BLE001
        result.warnings.append(f"{source}: {exc}")
        return []
    if isinstance(value, list):
        result.sources_used.append(source)
        return [v for v in value if isinstance(v, dict)]
    return []


async def _safe_value(coro: Awaitable[Any], result: RouterResult, source: str) -> dict[str, Any] | None:
    try:
        value = await coro
    except Exception as exc:  # noqa: BLE001
        result.warnings.append(f"{source}: {exc}")
        return None
    if isinstance(value, dict):
        result.sources_used.append(source)
        return value
    return None



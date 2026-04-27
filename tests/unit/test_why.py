from __future__ import annotations

import asyncio
from pathlib import Path

from engram.tools.engram_ns import register_engram_tools
from engram.tools.registry import ToolRegistry


def _build(
    tmp_path: Path,
    *,
    symbol=None,
    memories=None,
    facts=None,
    chunks=None,
) -> ToolRegistry:
    async def drawer_lookup(_drawer_id: str):
        return None

    async def symbol_lookup(name_path: str, relative_path: str):
        return symbol

    async def mem_search(query: str):
        return list(memories or [])

    async def kg_query(subject: str):
        return list(facts or [])

    async def vec_search(query: str, limit: int):
        return list(chunks or [])

    registry = ToolRegistry()
    register_engram_tools(
        registry,
        tmp_path / "anchors.sqlite",
        supervisor=None,
        drawer_lookup=drawer_lookup,
        symbol_lookup=symbol_lookup,
        mem_search=mem_search,
        kg_query=kg_query,
        vec_search=vec_search,
    )
    return registry


def test_why_path_b_happy(tmp_path: Path) -> None:
    reg = _build(
        tmp_path,
        symbol={"name_path": "Foo/process", "relative_path": "src/foo.py", "kind": 12},
        memories=[{"drawer_id": "D1", "content": "batch size 100 because ..."}],
        facts=[
            {
                "subject": "Foo/process",
                "predicate": "decided_to_batch_by",
                "object": "100",
            }
        ],
    )
    tool = reg.get("engram.why")
    resp = asyncio.run(
        tool.handler(  # type: ignore[union-attr]
            {"name_path": "Foo/process", "relative_path": "src/foo.py"}
        )
    )
    assert resp["meta"]["path_used"] == "B"
    assert resp["result"]["symbol"]["name_path"] == "Foo/process"
    assert len(resp["result"]["memories"]) == 1
    assert resp["result"]["facts"][0]["predicate"] == "decided_to_batch_by"
    assert resp["result"]["chunks"] == []
    assert resp["result"]["fused"] == []


def test_why_symbol_not_found(tmp_path: Path) -> None:
    reg = _build(tmp_path, symbol=None)
    tool = reg.get("engram.why")
    resp = asyncio.run(
        tool.handler(  # type: ignore[union-attr]
            {"name_path": "Bogus/missing", "relative_path": "src/nope.py"}
        )
    )
    assert resp["error"]["code"] == "symbol-not-found"


def test_why_requires_some_input(tmp_path: Path) -> None:
    reg = _build(tmp_path)
    tool = reg.get("engram.why")
    resp = asyncio.run(tool.handler({}))  # type: ignore[union-attr]
    assert resp["error"]["code"] == "invalid-input"


def test_why_path_a_returns_chunks(tmp_path: Path) -> None:
    reg = _build(
        tmp_path,
        chunks=[
            {"relative_path": "a.py", "start_line": 1, "end_line": 10, "text": "..."},
            {"relative_path": "b.py", "start_line": 5, "end_line": 20, "text": "..."},
        ],
    )
    tool = reg.get("engram.why")
    resp = asyncio.run(
        tool.handler({"free_query": "rate limiter"})  # type: ignore[union-attr]
    )
    assert resp["meta"]["path_used"] == "A"
    assert len(resp["result"]["chunks"]) == 2
    assert resp["result"]["chunks"][0]["relative_path"] == "a.py"
    assert resp["result"]["memories"] == []
    assert resp["result"]["facts"] == []
    assert resp["result"]["fused"] == []
    assert resp["result"]["symbol"] is None


def test_why_path_c_fuses_all_sources(tmp_path: Path) -> None:
    reg = _build(
        tmp_path,
        symbol={"name_path": "Foo/process", "relative_path": "src/foo.py", "kind": 12},
        memories=[{"drawer_id": "D1", "content": "batched at 100 due to upstream cap"}],
        facts=[
            {
                "subject": "Foo/process",
                "predicate": "decided_to_batch_by",
                "object": "100",
            }
        ],
        chunks=[
            {"relative_path": "src/foo.py", "start_line": 42, "end_line": 58, "text": "..."}
        ],
    )
    tool = reg.get("engram.why")
    resp = asyncio.run(
        tool.handler(  # type: ignore[union-attr]
            {
                "name_path": "Foo/process",
                "relative_path": "src/foo.py",
                "free_query": "why batch by 100?",
            }
        )
    )
    assert resp["meta"]["path_used"] == "C"
    assert resp["result"]["symbol"]["name_path"] == "Foo/process"
    assert len(resp["result"]["chunks"]) == 1
    assert len(resp["result"]["memories"]) == 1
    assert len(resp["result"]["facts"]) == 1
    fused = resp["result"]["fused"]
    assert len(fused) == 3
    item = fused[0]
    assert set(item.keys()) == {"item_id", "score", "ranks_by_source"}
    assert isinstance(item["item_id"], str)
    assert isinstance(item["score"], float)
    assert isinstance(item["ranks_by_source"], dict)


def test_why_description_passes_lint(tmp_path: Path) -> None:
    from engram.tools.lint import lint_engram_namespace

    reg = _build(tmp_path)
    issues = lint_engram_namespace(reg)
    assert issues == [], "\n".join(issues)


def _build_with_counters(
    tmp_path: Path,
    *,
    cache=None,
    bus=None,
    symbol=None,
    memories=None,
    facts=None,
    chunks=None,
):
    counters = {"symbol": 0, "mem": 0, "kg": 0, "vec": 0}

    async def drawer_lookup(_drawer_id: str):
        return None

    async def symbol_lookup(name_path: str, relative_path: str):
        counters["symbol"] += 1
        return symbol

    async def mem_search(query: str):
        counters["mem"] += 1
        return list(memories or [])

    async def kg_query(subject: str):
        counters["kg"] += 1
        return list(facts or [])

    async def vec_search(query: str, limit: int):
        counters["vec"] += 1
        return list(chunks or [])

    registry = ToolRegistry()
    register_engram_tools(
        registry,
        tmp_path / "anchors.sqlite",
        supervisor=None,
        drawer_lookup=drawer_lookup,
        symbol_lookup=symbol_lookup,
        mem_search=mem_search,
        kg_query=kg_query,
        vec_search=vec_search,
        bus=bus,
        cache=cache,
    )
    return registry, counters


def test_why_cache_hit_skips_dispatch(tmp_path: Path) -> None:
    from engram.router.cache import LRUCache

    cache = LRUCache(max_entries=8)
    reg, counters = _build_with_counters(
        tmp_path,
        cache=cache,
        symbol={"name_path": "Foo/process", "relative_path": "src/foo.py", "kind": 12},
        memories=[{"drawer_id": "D1"}],
        facts=[{"subject": "Foo/process", "predicate": "p", "object": "o"}],
    )
    tool = reg.get("engram.why")
    args = {"name_path": "Foo/process", "relative_path": "src/foo.py"}

    asyncio.run(tool.handler(args))  # type: ignore[union-attr]
    after_first = dict(counters)
    asyncio.run(tool.handler(args))  # type: ignore[union-attr]

    # symbol_lookup is called once for the not-found guard AND once inside
    # dispatcher path-B on the cold call; the warm call should hit cache and
    # only invoke symbol_lookup for the guard, not the dispatcher.
    assert counters["mem"] == after_first["mem"]
    assert counters["kg"] == after_first["kg"]
    assert counters["vec"] == after_first["vec"]


def test_why_cache_evicts_on_file_replaced(tmp_path: Path) -> None:
    from engram.events import EVENT_FILE_REPLACED, HookBus
    from engram.router.cache import LRUCache

    bus = HookBus()
    cache = LRUCache(max_entries=8)
    cache.subscribe_to(bus)
    reg, counters = _build_with_counters(
        tmp_path,
        cache=cache,
        bus=bus,
        symbol={"name_path": "Foo/process", "relative_path": "src/foo.py", "kind": 12},
        memories=[{"drawer_id": "D1"}],
        facts=[{"subject": "Foo/process", "predicate": "p", "object": "o"}],
    )
    tool = reg.get("engram.why")
    args = {"name_path": "Foo/process", "relative_path": "src/foo.py"}

    asyncio.run(tool.handler(args))  # type: ignore[union-attr]
    asyncio.run(tool.handler(args))  # type: ignore[union-attr]
    warm_mem = counters["mem"]

    asyncio.run(bus.publish(EVENT_FILE_REPLACED, {"relative_path": "src/foo.py"}))

    asyncio.run(tool.handler(args))  # type: ignore[union-attr]
    assert counters["mem"] == warm_mem + 1


def test_why_cache_does_not_cache_symbol_not_found(tmp_path: Path) -> None:
    from engram.router.cache import LRUCache

    cache = LRUCache(max_entries=8)
    reg, counters = _build_with_counters(tmp_path, cache=cache, symbol=None)
    tool = reg.get("engram.why")
    args = {"name_path": "Bogus/missing", "relative_path": "src/nope.py"}

    r1 = asyncio.run(tool.handler(args))  # type: ignore[union-attr]
    r2 = asyncio.run(tool.handler(args))  # type: ignore[union-attr]
    assert r1["error"]["code"] == "symbol-not-found"
    assert r2["error"]["code"] == "symbol-not-found"
    # Both calls must hit symbol_lookup; the failure must not be cached.
    assert counters["symbol"] == 2

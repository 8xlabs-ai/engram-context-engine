from __future__ import annotations

import asyncio

from engram.router.dispatcher import RouterDispatcher


def _make_dispatcher(
    *,
    chunks=None,
    memories=None,
    facts=None,
    symbol=None,
    raises: set[str] | None = None,
) -> RouterDispatcher:
    raises = raises or set()

    async def vec_search(query: str, limit: int):
        if "vec" in raises:
            raise RuntimeError("vec down")
        return list(chunks or [])

    async def mem_search(query: str):
        if "mem" in raises:
            raise RuntimeError("mem down")
        return list(memories or [])

    async def kg_query(subject: str):
        if "kg" in raises:
            raise RuntimeError("kg down")
        return list(facts or [])

    async def symbol_lookup(name_path: str, relative_path: str):
        if "sym" in raises:
            raise RuntimeError("sym down")
        return symbol

    return RouterDispatcher(
        vec_search=vec_search,
        mem_search=mem_search,
        kg_query=kg_query,
        symbol_lookup=symbol_lookup,
    )


def test_path_a_runs_vec_only() -> None:
    d = _make_dispatcher(chunks=[{"relative_path": "src/foo.py", "start_line": 1, "end_line": 5}])
    r = asyncio.run(d.dispatch({"query": "parse json"}))
    assert r.path_used == "A"
    assert len(r.chunks) == 1
    assert r.memories == []


def test_path_b_runs_symbol_mem_kg() -> None:
    d = _make_dispatcher(
        symbol={"name_path": "Foo/process", "relative_path": "src/foo.py"},
        memories=[{"drawer_id": "D1"}],
        facts=[{"subject": "Foo/process", "predicate": "x", "object": "y"}],
    )
    r = asyncio.run(
        d.dispatch({"name_path": "Foo/process", "relative_path": "src/foo.py"})
    )
    assert r.path_used == "B"
    assert r.symbol["name_path"] == "Foo/process"
    assert len(r.memories) == 1
    assert len(r.facts) == 1


def test_path_c_fuses_sources() -> None:
    d = _make_dispatcher(
        chunks=[{"relative_path": "src/a.py", "start_line": 1, "end_line": 5}],
        memories=[{"drawer_id": "D1"}, {"drawer_id": "D2"}],
        facts=[{"subject": "Foo", "predicate": "p", "object": "v"}],
    )
    r = asyncio.run(
        d.dispatch({"name_path": "Foo/process", "query": "parse json"})
    )
    assert r.path_used == "C"
    assert r.fused, "fused list must be non-empty"
    assert len(r.fused) <= 20
    # All three sources contributed.
    sources_seen = set()
    for item in r.fused:
        sources_seen.update(item["ranks_by_source"].keys())
    assert sources_seen >= {"vec", "mem", "kg"}


def test_path_c_survives_one_source_failure() -> None:
    d = _make_dispatcher(
        chunks=[{"relative_path": "src/a.py", "start_line": 1, "end_line": 5}],
        memories=[{"drawer_id": "D1"}],
        facts=[{"subject": "Foo", "predicate": "p", "object": "v"}],
        raises={"vec"},
    )
    r = asyncio.run(
        d.dispatch({"name_path": "Foo/process", "query": "parse json"})
    )
    assert r.path_used == "C"
    assert any("claude_context" in w for w in r.warnings)
    # Fusion still runs over surviving sources.
    sources_seen = set()
    for item in r.fused:
        sources_seen.update(item["ranks_by_source"].keys())
    assert "vec" not in sources_seen
    assert sources_seen.issuperset({"mem", "kg"})


def test_path_a_empty_query_short_circuits() -> None:
    d = _make_dispatcher(chunks=[{"relative_path": "x"}])
    r = asyncio.run(d.dispatch({}))
    assert r.path_used == "A"
    assert r.chunks == []  # empty query skips the call


def test_path_c_empty_sources_returns_empty_fused() -> None:
    d = _make_dispatcher()
    r = asyncio.run(d.dispatch({"name_path": "Foo", "query": "x"}))
    assert r.path_used == "C"
    assert r.fused == []

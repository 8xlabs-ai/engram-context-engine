from __future__ import annotations

import asyncio
from pathlib import Path

from engram.tools.engram_ns import register_engram_tools
from engram.tools.registry import ToolRegistry


def _build(tmp_path: Path, *, symbol=None, memories=None, facts=None) -> ToolRegistry:
    async def drawer_lookup(_drawer_id: str):
        return None

    async def symbol_lookup(name_path: str, relative_path: str):
        return symbol

    async def mem_search(query: str):
        return list(memories or [])

    async def kg_query(subject: str):
        return list(facts or [])

    registry = ToolRegistry()
    register_engram_tools(
        registry,
        tmp_path / "anchors.sqlite",
        supervisor=None,
        drawer_lookup=drawer_lookup,
        symbol_lookup=symbol_lookup,
        mem_search=mem_search,
        kg_query=kg_query,
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


def test_why_free_query_only_returns_mem_search(tmp_path: Path) -> None:
    reg = _build(tmp_path, memories=[{"drawer_id": "D9", "content": "hi"}])
    tool = reg.get("engram.why")
    resp = asyncio.run(
        tool.handler({"free_query": "rename foo"})  # type: ignore[union-attr]
    )
    assert resp["meta"]["path_used"] == "A"
    assert resp["result"]["memories"][0]["drawer_id"] == "D9"


def test_why_description_passes_lint(tmp_path: Path) -> None:
    from engram.tools.lint import lint_engram_namespace

    reg = _build(tmp_path)
    issues = lint_engram_namespace(reg)
    assert issues == [], "\n".join(issues)

from __future__ import annotations

import asyncio
from pathlib import Path

from engram.tools.engram_ns import register_engram_tools
from engram.tools.registry import ToolRegistry


def _build(tmp_path: Path, *, facts, chunks_by_query, symbol):
    async def drawer_lookup(_drawer_id):
        return None

    async def symbol_lookup(name_path, relative_path):
        return symbol

    async def mem_search(_q):
        return []

    async def kg_query(subject):
        return list(facts)

    async def vec_search(q: str, limit: int):
        return list(chunks_by_query.get(q, []))

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


def test_where_decision_returns_implementations(tmp_path: Path) -> None:
    reg = _build(
        tmp_path,
        facts=[
            {
                "subject": "graphql_migration",
                "predicate": "decided_for",
                "object": "api_v2",
            }
        ],
        chunks_by_query={
            "graphql_migration": [
                {"relative_path": "src/api/v2.py", "start_line": 10, "end_line": 40}
            ],
            "api_v2": [
                {"relative_path": "src/api/v2.py", "start_line": 10, "end_line": 40}
            ],
        },
        symbol={"name_path": "Api/v2", "relative_path": "src/api/v2.py", "kind": 12},
    )
    tool = reg.get("engram.where_does_decision_apply")
    resp = asyncio.run(
        tool.handler({"decision_entity": "graphql_migration"})  # type: ignore[union-attr]
    )
    impl = resp["result"]["implementations"]
    assert len(impl) == 1  # de-duped by (path:start_line)
    assert impl[0]["chunk"]["relative_path"] == "src/api/v2.py"
    assert resp["meta"]["path_used"] == "C"


def test_where_decision_invalid_input(tmp_path: Path) -> None:
    reg = _build(tmp_path, facts=[], chunks_by_query={}, symbol=None)
    tool = reg.get("engram.where_does_decision_apply")
    resp = asyncio.run(tool.handler({}))  # type: ignore[union-attr]
    assert resp["error"]["code"] == "invalid-input"


def test_where_decision_empty_facts_returns_no_implementations(tmp_path: Path) -> None:
    reg = _build(
        tmp_path,
        facts=[],
        chunks_by_query={"x": []},
        symbol=None,
    )
    tool = reg.get("engram.where_does_decision_apply")
    resp = asyncio.run(tool.handler({"decision_entity": "x"}))  # type: ignore[union-attr]
    assert resp["result"]["implementations"] == []


def test_where_decision_passes_lint(tmp_path: Path) -> None:
    from engram.tools.lint import lint_engram_namespace

    reg = _build(tmp_path, facts=[], chunks_by_query={}, symbol=None)
    issues = lint_engram_namespace(reg)
    assert issues == [], "\n".join(issues)

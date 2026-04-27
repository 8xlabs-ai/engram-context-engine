from __future__ import annotations

import asyncio
from pathlib import Path

from engram.tools.engram_ns import register_engram_tools
from engram.tools.registry import ToolRegistry


def _build(
    tmp_path: Path,
    *,
    facts,
    chunks_by_query,
    symbol=None,
    chunk_symbol_resolver=None,
):
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

    if chunk_symbol_resolver is None:
        async def chunk_symbol_resolver(_chunk):
            return None

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
        chunk_symbol_resolver=chunk_symbol_resolver,
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
    )
    tool = reg.get("engram.where_does_decision_apply")
    resp = asyncio.run(
        tool.handler({"decision_entity": "graphql_migration"})  # type: ignore[union-attr]
    )
    impl = resp["result"]["implementations"]
    assert len(impl) == 1  # de-duped by (path:start_line)
    assert impl[0]["chunk"]["relative_path"] == "src/api/v2.py"
    assert resp["meta"]["path_used"] == "C"


def test_where_decision_resolves_symbol_from_line_range(tmp_path: Path) -> None:
    """The fallback resolver receives the chunk and returns the enclosing symbol
    based on its line range — never on the decision-entity term."""
    seen_chunks = []

    async def resolver(chunk):
        seen_chunks.append(chunk)
        if (
            chunk.get("relative_path") == "src/api/v2.py"
            and chunk.get("start_line") == 10
        ):
            return {
                "name_path": "Api/v2",
                "relative_path": "src/api/v2.py",
                "kind": 12,
                "source": "serena_live",
            }
        return None

    reg = _build(
        tmp_path,
        facts=[],
        chunks_by_query={
            "gdpr_retention_30d": [
                {"relative_path": "src/api/v2.py", "start_line": 10, "end_line": 40}
            ]
        },
        chunk_symbol_resolver=resolver,
    )
    tool = reg.get("engram.where_does_decision_apply")
    resp = asyncio.run(
        tool.handler({"decision_entity": "gdpr_retention_30d"})  # type: ignore[union-attr]
    )
    impl = resp["result"]["implementations"]
    assert len(impl) == 1
    assert impl[0]["symbol"] is not None
    assert impl[0]["symbol"]["name_path"] == "Api/v2"
    assert impl[0]["symbol"]["source"] == "serena_live"
    # Resolver got the chunk dict, not the term string.
    assert seen_chunks[0]["start_line"] == 10


def test_where_decision_skips_resolver_when_chunk_has_enclosing_symbol(
    tmp_path: Path,
) -> None:
    """If the chunk already carries `enclosing_symbol` (from the enriched
    vec.search proxy), the fallback resolver is not invoked."""
    resolver_called = False

    async def resolver(_chunk):
        nonlocal resolver_called
        resolver_called = True
        return None

    pre_enriched_symbol = {
        "name_path": "Pre/Enriched",
        "relative_path": "src/x.py",
        "kind": 12,
        "source": "anchor_cache",
    }
    reg = _build(
        tmp_path,
        facts=[],
        chunks_by_query={
            "x": [
                {
                    "relative_path": "src/x.py",
                    "start_line": 1,
                    "end_line": 10,
                    "enclosing_symbol": pre_enriched_symbol,
                }
            ]
        },
        chunk_symbol_resolver=resolver,
    )
    tool = reg.get("engram.where_does_decision_apply")
    resp = asyncio.run(
        tool.handler({"decision_entity": "x"})  # type: ignore[union-attr]
    )
    impl = resp["result"]["implementations"]
    assert len(impl) == 1
    assert impl[0]["symbol"] == pre_enriched_symbol
    assert resolver_called is False


def test_where_decision_invalid_input(tmp_path: Path) -> None:
    reg = _build(tmp_path, facts=[], chunks_by_query={})
    tool = reg.get("engram.where_does_decision_apply")
    resp = asyncio.run(tool.handler({}))  # type: ignore[union-attr]
    assert resp["error"]["code"] == "invalid-input"


def test_where_decision_empty_facts_returns_no_implementations(tmp_path: Path) -> None:
    reg = _build(
        tmp_path,
        facts=[],
        chunks_by_query={"x": []},
    )
    tool = reg.get("engram.where_does_decision_apply")
    resp = asyncio.run(tool.handler({"decision_entity": "x"}))  # type: ignore[union-attr]
    assert resp["result"]["implementations"] == []


def test_where_decision_passes_lint(tmp_path: Path) -> None:
    from engram.tools.lint import lint_engram_namespace

    reg = _build(tmp_path, facts=[], chunks_by_query={})
    issues = lint_engram_namespace(reg)
    assert issues == [], "\n".join(issues)

from __future__ import annotations

import asyncio
from pathlib import Path

from engram.tools.engram_ns import register_engram_tools
from engram.tools.registry import ToolRegistry


def _fake_drawer(store: dict[str, dict]):
    async def lookup(drawer_id: str):
        return store.get(drawer_id)
    return lookup


def _fake_symbol():
    async def lookup(name_path: str, relative_path: str):
        return {"name_path": name_path, "relative_path": relative_path, "kind": 12}
    return lookup


def _build(tmp_path: Path, drawers: dict[str, dict]) -> ToolRegistry:
    registry = ToolRegistry()
    register_engram_tools(
        registry,
        tmp_path / "anchors.sqlite",
        supervisor=None,
        drawer_lookup=_fake_drawer(drawers),
        symbol_lookup=_fake_symbol(),
    )
    return registry


def test_anchor_memory_to_symbol_idempotent(tmp_path: Path) -> None:
    drawers = {"D1": {"wing": "engram", "room": "decisions"}}
    reg = _build(tmp_path, drawers)
    tool = reg.get("engram.anchor_memory_to_symbol")
    args = {
        "drawer_id": "D1",
        "name_path": "Foo/process",
        "relative_path": "src/foo.py",
    }
    first = asyncio.run(tool.handler(args))  # type: ignore[union-attr]
    second = asyncio.run(tool.handler(args))  # type: ignore[union-attr]
    assert first["result"]["anchor_id"] == second["result"]["anchor_id"]
    assert first["result"]["symbol_id"] == second["result"]["symbol_id"]


def test_anchor_memory_to_symbol_missing_drawer(tmp_path: Path) -> None:
    reg = _build(tmp_path, drawers={})
    tool = reg.get("engram.anchor_memory_to_symbol")
    resp = asyncio.run(
        tool.handler(  # type: ignore[union-attr]
            {
                "drawer_id": "missing",
                "name_path": "Foo/process",
                "relative_path": "src/foo.py",
            }
        )
    )
    assert resp["error"]["code"] == "drawer-not-found"


def test_anchor_memory_to_chunk_happy_path(tmp_path: Path) -> None:
    drawers = {"D1": {"wing": "w", "room": "r"}}
    reg = _build(tmp_path, drawers)
    tool = reg.get("engram.anchor_memory_to_chunk")
    resp = asyncio.run(
        tool.handler(  # type: ignore[union-attr]
            {
                "drawer_id": "D1",
                "relative_path": "src/foo.py",
                "start_line": 10,
                "end_line": 40,
                "language": "python",
            }
        )
    )
    assert "anchor_id" in resp["result"]


def test_anchor_memory_to_chunk_validates_lines(tmp_path: Path) -> None:
    drawers = {"D1": {"wing": "w", "room": "r"}}
    reg = _build(tmp_path, drawers)
    tool = reg.get("engram.anchor_memory_to_chunk")
    resp = asyncio.run(
        tool.handler(  # type: ignore[union-attr]
            {
                "drawer_id": "D1",
                "relative_path": "src/foo.py",
                "start_line": "nope",
                "end_line": 40,
            }
        )
    )
    assert resp["error"]["code"] == "invalid-input"


def test_symbol_history_returns_rename_chain(tmp_path: Path) -> None:
    from engram.link.store import init_db, rename_symbol, upsert_symbol

    conn = init_db(tmp_path / "anchors.sqlite")
    try:
        sid = upsert_symbol(
            conn, name_path="Foo/process", relative_path="src/foo.py", kind=12
        )
        rename_symbol(conn, sid, new_name_path="Foo/run")
    finally:
        conn.close()

    reg = _build(tmp_path, drawers={})
    tool = reg.get("engram.symbol_history")
    resp = asyncio.run(
        tool.handler(  # type: ignore[union-attr]
            {"name_path": "Foo/run", "relative_path": "src/foo.py"}
        )
    )
    history = resp["result"]["history"]
    assert len(history) == 2
    assert history[-1]["source"] == "engram-rename"
    assert history[-1]["old_name_path"] == "Foo/process"


def test_symbol_history_unknown_symbol(tmp_path: Path) -> None:
    reg = _build(tmp_path, drawers={})
    tool = reg.get("engram.symbol_history")
    resp = asyncio.run(
        tool.handler(  # type: ignore[union-attr]
            {"name_path": "Nope/missing", "relative_path": "src/nope.py"}
        )
    )
    assert resp["error"]["code"] == "symbol-not-found"


def test_all_engram_tools_pass_description_lint(tmp_path: Path) -> None:
    from engram.tools.lint import lint_engram_namespace

    reg = _build(tmp_path, drawers={})
    issues = lint_engram_namespace(reg)
    assert issues == [], "\n".join(issues)

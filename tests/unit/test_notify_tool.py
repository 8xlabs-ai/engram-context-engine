from __future__ import annotations

import asyncio
from pathlib import Path

from engram.events import HookBus
from engram.link.store import init_db
from engram.tools.notify import make_notify_handler, register_notify_tools
from engram.tools.registry import ToolRegistry
from engram.workers.change_log import attach_change_logger


def _setup(tmp_path: Path) -> tuple[Path, ToolRegistry, HookBus]:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    bus = HookBus()
    attach_change_logger(bus, db)
    registry = ToolRegistry()
    register_notify_tools(registry, db, bus)
    return db, registry, bus


def test_notify_handler_publishes_to_bus_through_subscriber(tmp_path: Path) -> None:
    db, registry, bus = _setup(tmp_path)
    handler = make_notify_handler(bus)

    async def run() -> dict:
        return await handler(
            {
                "relative_path": "src/foo.py",
                "change_type": "edit",
                "source": "manual",
                "conversation_id": "conv_xyz",
            }
        )

    result = asyncio.run(run())
    assert result["accepted"] is True

    spec = registry.get("engram.changes_in_conversation")
    assert spec is not None
    res = asyncio.run(spec.handler({"conversation_id": "conv_xyz"}))
    assert res["result"]["conversation_id"] == "conv_xyz"
    assert len(res["result"]["changes"]) == 1
    assert res["result"]["changes"][0]["relative_path"] == "src/foo.py"


def test_notify_tool_validates_change_type(tmp_path: Path) -> None:
    _, registry, _ = _setup(tmp_path)
    spec = registry.get("engram.notify_file_changed")
    assert spec is not None
    res = asyncio.run(
        spec.handler({"relative_path": "src/foo.py", "change_type": "blast"})
    )
    assert res["error"]["code"] == "invalid-input"


def test_notify_tool_requires_relative_path(tmp_path: Path) -> None:
    _, registry, _ = _setup(tmp_path)
    spec = registry.get("engram.notify_file_changed")
    assert spec is not None
    res = asyncio.run(spec.handler({"change_type": "edit"}))
    assert res["error"]["code"] == "invalid-input"


def test_changes_in_conversation_returns_empty_when_db_absent(tmp_path: Path) -> None:
    db = tmp_path / "missing.sqlite"
    bus = HookBus()
    registry = ToolRegistry()
    register_notify_tools(registry, db, bus)
    spec = registry.get("engram.changes_in_conversation")
    assert spec is not None
    res = asyncio.run(spec.handler({"conversation_id": "x"}))
    assert res["result"]["changes"] == []

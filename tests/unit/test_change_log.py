from __future__ import annotations

import asyncio
from pathlib import Path

from engram.events import EVENT_FILE_REPLACED, HookBus
from engram.link.store import (
    changes_for_conversation,
    dirty_file_paths,
    init_db,
    open_db,
    upsert_symbol,
)
from engram.workers.change_log import attach_change_logger


def _publish(bus: HookBus, payload: dict) -> None:
    asyncio.run(bus.publish(EVENT_FILE_REPLACED, payload))


def test_change_logger_writes_row_and_marks_dirty(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()

    bus = HookBus()
    attach_change_logger(bus, db)

    _publish(
        bus,
        {
            "relative_path": "src/foo.py",
            "change_type": "edit",
            "source": "engram_write_hook",
            "tool": "replace_symbol_body",
            "agent": "engram",
            "ts": 1.0,
        },
    )

    conn = open_db(db)
    try:
        rows = conn.execute(
            "SELECT relative_path, change_type, source, tool, agent FROM change_log"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["relative_path"] == "src/foo.py"
        assert rows[0]["source"] == "engram_write_hook"
        assert dirty_file_paths(conn) == ["src/foo.py"]
    finally:
        conn.close()


def test_change_logger_records_conversation_id(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()

    bus = HookBus()
    attach_change_logger(bus, db)

    _publish(
        bus,
        {
            "relative_path": "src/bar.py",
            "change_type": "edit",
            "source": "claude_code_hook",
            "tool": "Edit",
            "agent": "claude_code",
            "conversation_id": "conv_123",
            "tool_use_id": "toolu_xyz",
        },
    )

    conn = open_db(db)
    try:
        rows = changes_for_conversation(conn, "conv_123", limit=10)
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["relative_path"] == "src/bar.py"
    assert rows[0]["tool_use_id"] == "toolu_xyz"
    assert rows[0]["reindex_state"] == "pending"


def test_change_logger_tombstones_symbols_on_delete(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    conn = init_db(db)
    upsert_symbol(conn, name_path="Foo/process", relative_path="src/foo.py", kind=12)
    conn.close()

    bus = HookBus()
    attach_change_logger(bus, db)

    _publish(
        bus,
        {
            "relative_path": "src/foo.py",
            "change_type": "delete",
            "source": "claude_code_hook",
        },
    )

    conn = open_db(db)
    try:
        row = conn.execute(
            "SELECT tombstoned_at FROM symbols WHERE relative_path = 'src/foo.py'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["tombstoned_at"] is not None


def test_change_logger_ignores_payload_without_path(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()

    bus = HookBus()
    attach_change_logger(bus, db)

    _publish(bus, {"change_type": "edit"})

    conn = open_db(db)
    try:
        count = conn.execute("SELECT COUNT(*) FROM change_log").fetchone()[0]
    finally:
        conn.close()
    assert count == 0

from __future__ import annotations

import asyncio
from pathlib import Path

from engram.events import EVENT_FILE_REPLACED, HookBus
from engram.link.store import (
    dirty_file_paths,
    init_db,
    open_db,
    upsert_symbol,
)
from engram.workers.change_log import attach_change_logger
from engram.workers.reconciler import collect_dirty_paths, reconcile


def test_reconcile_chunks_with_paths_clears_dirty_files(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    conn = init_db(db)
    sym_id = upsert_symbol(
        conn, name_path="Foo/process", relative_path="src/foo.py", kind=12
    )
    # Tombstone so the chunk reconciler will sweep it.
    conn.execute(
        "UPDATE symbols SET tombstoned_at = datetime('now') WHERE symbol_id = ?",
        (sym_id,),
    )
    conn.execute(
        "INSERT INTO anchors_symbol_chunk "
        "(symbol_id, relative_path, start_line, end_line, language, index_generation) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (sym_id, "src/foo.py", 1, 10, "py", 0),
    )
    conn.execute(
        "INSERT INTO change_log "
        "(relative_path, change_type, source) VALUES (?, ?, ?)",
        ("src/foo.py", "edit", "manual"),
    )
    conn.execute(
        "INSERT INTO dirty_files (relative_path) VALUES (?)", ("src/foo.py",)
    )
    conn.close()

    report = asyncio.run(
        reconcile(db, scope="chunks", paths=["src/foo.py"])
    )
    assert report.changed["anchors"] == 1

    conn = open_db(db)
    try:
        assert dirty_file_paths(conn) == []
        row = conn.execute(
            "SELECT reindex_state FROM change_log WHERE relative_path = 'src/foo.py'"
        ).fetchone()
    finally:
        conn.close()
    assert row["reindex_state"] == "reindexed"


def test_collect_dirty_paths_after_subscriber(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    bus = HookBus()
    attach_change_logger(bus, db)

    asyncio.run(
        bus.publish(
            EVENT_FILE_REPLACED,
            {
                "relative_path": "src/x.py",
                "change_type": "edit",
                "source": "manual",
            },
        )
    )

    assert collect_dirty_paths(db) == ["src/x.py"]

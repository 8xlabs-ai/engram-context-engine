from __future__ import annotations

from pathlib import Path

import pytest

from engram.link.store import (
    append_history,
    get_symbol,
    get_symbol_by_id,
    history_for,
    init_db,
    memory_anchors_for_symbol,
    meta_get,
    meta_set,
    rename_symbol,
    tombstone_symbol,
    upsert_anchor_memory_chunk,
    upsert_anchor_symbol_memory,
    upsert_symbol,
)


def _conn(tmp_path: Path):
    return init_db(tmp_path / "anchors.sqlite")


def test_upsert_symbol_creates_once(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        a = upsert_symbol(
            conn, name_path="Foo/process", relative_path="src/foo.py", kind=12
        )
        b = upsert_symbol(
            conn, name_path="Foo/process", relative_path="src/foo.py", kind=12
        )
        assert a == b
        rows = conn.execute("SELECT COUNT(*) AS n FROM symbols").fetchone()
        assert rows["n"] == 1
        hist = history_for(conn, a)
        assert len(hist) == 1
        assert hist[0].source == "discovery"
        assert hist[0].new_name_path == "Foo/process"
    finally:
        conn.close()


def test_rename_symbol_updates_row_and_history(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        sid = upsert_symbol(
            conn, name_path="Foo/process", relative_path="src/foo.py", kind=12
        )
        rename_symbol(conn, sid, new_name_path="Foo/run")
        sym = get_symbol_by_id(conn, sid)
        assert sym is not None
        assert sym.name_path == "Foo/run"
        hist = history_for(conn, sid)
        assert len(hist) == 2
        assert hist[-1].source == "engram-rename"
        assert hist[-1].old_name_path == "Foo/process"
        assert hist[-1].new_name_path == "Foo/run"
    finally:
        conn.close()


def test_rename_symbol_with_path_move(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        sid = upsert_symbol(
            conn, name_path="Foo/process", relative_path="src/foo.py", kind=12
        )
        rename_symbol(conn, sid, new_name_path="Foo/process", new_path="src/pipeline/foo.py")
        sym = get_symbol_by_id(conn, sid)
        assert sym.relative_path == "src/pipeline/foo.py"
        hist = history_for(conn, sid)
        assert hist[-1].old_path == "src/foo.py"
        assert hist[-1].new_path == "src/pipeline/foo.py"
    finally:
        conn.close()


def test_tombstone_allows_fresh_insert_at_same_identity(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        sid = upsert_symbol(
            conn, name_path="Foo/process", relative_path="src/foo.py", kind=12
        )
        tombstone_symbol(conn, sid)
        assert get_symbol(conn, "Foo/process", "src/foo.py") is None

        sid2 = upsert_symbol(
            conn, name_path="Foo/process", relative_path="src/foo.py", kind=12
        )
        assert sid2 != sid
        hist = history_for(conn, sid)
        assert hist[-1].source == "engram-delete"
    finally:
        conn.close()


def test_anchor_symbol_memory_is_idempotent(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        sid = upsert_symbol(
            conn, name_path="Foo/process", relative_path="src/foo.py", kind=12
        )
        a = upsert_anchor_symbol_memory(
            conn,
            symbol_id=sid,
            drawer_id="D1",
            wing="engram",
            room="decisions",
            created_by="explicit",
        )
        b = upsert_anchor_symbol_memory(
            conn,
            symbol_id=sid,
            drawer_id="D1",
            wing="engram",
            room="decisions",
            created_by="explicit",
        )
        assert a == b
        anchors = memory_anchors_for_symbol(conn, sid)
        assert len(anchors) == 1
        assert anchors[0]["drawer_id"] == "D1"
    finally:
        conn.close()


def test_anchor_memory_chunk_is_idempotent(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        a = upsert_anchor_memory_chunk(
            conn,
            drawer_id="D1",
            relative_path="src/foo.py",
            start_line=10,
            end_line=40,
            language="python",
            index_generation=0,
        )
        b = upsert_anchor_memory_chunk(
            conn,
            drawer_id="D1",
            relative_path="src/foo.py",
            start_line=10,
            end_line=40,
            language="python",
            index_generation=0,
        )
        assert a == b
    finally:
        conn.close()


def test_meta_get_set(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        assert meta_get(conn, "mempalace_wal_cursor") == "0"
        meta_set(conn, "mempalace_wal_cursor", "128")
        assert meta_get(conn, "mempalace_wal_cursor") == "128"
        meta_set(conn, "new_key", "hello")
        assert meta_get(conn, "new_key") == "hello"
    finally:
        conn.close()


def test_rename_unknown_symbol_raises(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        with pytest.raises(ValueError, match="not found"):
            rename_symbol(conn, 9999, new_name_path="nope")
    finally:
        conn.close()

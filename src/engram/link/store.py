from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

META_SEEDS: tuple[tuple[str, str], ...] = (
    ("mempalace_wal_cursor", "0"),
    ("last_reconcile_at", "1970-01-01T00:00:00Z"),
    ("claude_context_index_generation", "0"),
    ("cc_hook_inbox_cursor", "0"),
)


@dataclass(frozen=True)
class SymbolRow:
    symbol_id: int
    name_path: str
    relative_path: str
    kind: int
    tombstoned_at: str | None


@dataclass(frozen=True)
class HistoryRow:
    history_id: int
    symbol_id: int
    at_time: str
    old_name_path: str | None
    new_name_path: str | None
    old_path: str | None
    new_path: str | None
    source: str


def schema_sql() -> str:
    return files("engram.link").joinpath("schema.sql").read_text(encoding="utf-8")


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: Path) -> sqlite3.Connection:
    conn = open_db(path)
    conn.executescript(schema_sql())
    conn.executemany(
        "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
        META_SEEDS,
    )
    return conn


# -----------------------------------------------------------------------------
# symbols
# -----------------------------------------------------------------------------


def upsert_symbol(
    conn: sqlite3.Connection,
    *,
    name_path: str,
    relative_path: str,
    kind: int,
) -> int:
    """Insert the symbol if absent (live only), refresh last_seen_at if present.

    Returns the symbol_id. A tombstoned row with the same identity does not
    collide — it can coexist with a live one thanks to the partial unique
    index.
    """
    row = conn.execute(
        "SELECT symbol_id FROM symbols "
        "WHERE name_path = ? AND relative_path = ? AND tombstoned_at IS NULL",
        (name_path, relative_path),
    ).fetchone()
    if row is not None:
        conn.execute(
            "UPDATE symbols SET last_seen_at = datetime('now') WHERE symbol_id = ?",
            (row["symbol_id"],),
        )
        return int(row["symbol_id"])

    cursor = conn.execute(
        "INSERT INTO symbols (name_path, relative_path, kind) VALUES (?, ?, ?)",
        (name_path, relative_path, kind),
    )
    symbol_id = int(cursor.lastrowid)
    append_history(
        conn,
        symbol_id=symbol_id,
        source="discovery",
        new_name_path=name_path,
        new_path=relative_path,
    )
    return symbol_id


def get_symbol(
    conn: sqlite3.Connection, name_path: str, relative_path: str
) -> SymbolRow | None:
    row = conn.execute(
        "SELECT symbol_id, name_path, relative_path, kind, tombstoned_at "
        "FROM symbols WHERE name_path = ? AND relative_path = ? "
        "AND tombstoned_at IS NULL",
        (name_path, relative_path),
    ).fetchone()
    return _as_symbol(row)


def get_symbol_by_id(conn: sqlite3.Connection, symbol_id: int) -> SymbolRow | None:
    row = conn.execute(
        "SELECT symbol_id, name_path, relative_path, kind, tombstoned_at "
        "FROM symbols WHERE symbol_id = ?",
        (symbol_id,),
    ).fetchone()
    return _as_symbol(row)


def rename_symbol(
    conn: sqlite3.Connection,
    symbol_id: int,
    *,
    new_name_path: str,
    new_path: str | None = None,
    source: str = "engram-rename",
) -> None:
    current = get_symbol_by_id(conn, symbol_id)
    if current is None:
        raise ValueError(f"symbol_id {symbol_id} not found")
    target_path = new_path or current.relative_path
    conn.execute(
        "UPDATE symbols SET name_path = ?, relative_path = ?, "
        "last_seen_at = datetime('now') WHERE symbol_id = ?",
        (new_name_path, target_path, symbol_id),
    )
    append_history(
        conn,
        symbol_id=symbol_id,
        source=source,
        old_name_path=current.name_path,
        new_name_path=new_name_path,
        old_path=current.relative_path if new_path else None,
        new_path=new_path,
    )


def tombstone_symbol(
    conn: sqlite3.Connection, symbol_id: int, *, source: str = "engram-delete"
) -> None:
    current = get_symbol_by_id(conn, symbol_id)
    if current is None or current.tombstoned_at is not None:
        return
    conn.execute(
        "UPDATE symbols SET tombstoned_at = datetime('now') WHERE symbol_id = ?",
        (symbol_id,),
    )
    append_history(
        conn,
        symbol_id=symbol_id,
        source=source,
        old_name_path=current.name_path,
        old_path=current.relative_path,
    )


# -----------------------------------------------------------------------------
# symbol_history
# -----------------------------------------------------------------------------


def append_history(
    conn: sqlite3.Connection,
    *,
    symbol_id: int,
    source: str,
    old_name_path: str | None = None,
    new_name_path: str | None = None,
    old_path: str | None = None,
    new_path: str | None = None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO symbol_history "
        "(symbol_id, old_name_path, new_name_path, old_path, new_path, source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (symbol_id, old_name_path, new_name_path, old_path, new_path, source),
    )
    return int(cursor.lastrowid)


def history_for(conn: sqlite3.Connection, symbol_id: int) -> list[HistoryRow]:
    rows = conn.execute(
        "SELECT history_id, symbol_id, at_time, old_name_path, new_name_path, "
        "old_path, new_path, source FROM symbol_history "
        "WHERE symbol_id = ? ORDER BY history_id ASC",
        (symbol_id,),
    ).fetchall()
    return [_as_history(r) for r in rows]


# -----------------------------------------------------------------------------
# anchors
# -----------------------------------------------------------------------------


def upsert_anchor_symbol_memory(
    conn: sqlite3.Connection,
    *,
    symbol_id: int,
    drawer_id: str,
    wing: str,
    room: str,
    created_by: str,
    confidence: float = 1.0,
) -> int:
    existing = conn.execute(
        "SELECT anchor_id FROM anchors_symbol_memory "
        "WHERE symbol_id = ? AND drawer_id = ?",
        (symbol_id, drawer_id),
    ).fetchone()
    if existing is not None:
        return int(existing["anchor_id"])
    cursor = conn.execute(
        "INSERT INTO anchors_symbol_memory "
        "(symbol_id, drawer_id, wing, room, created_by, confidence) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (symbol_id, drawer_id, wing, room, created_by, confidence),
    )
    return int(cursor.lastrowid)


def upsert_anchor_memory_chunk(
    conn: sqlite3.Connection,
    *,
    drawer_id: str,
    relative_path: str,
    start_line: int,
    end_line: int,
    language: str,
    index_generation: int,
) -> int:
    existing = conn.execute(
        "SELECT anchor_id FROM anchors_memory_chunk "
        "WHERE drawer_id = ? AND relative_path = ? AND start_line = ? AND end_line = ?",
        (drawer_id, relative_path, start_line, end_line),
    ).fetchone()
    if existing is not None:
        return int(existing["anchor_id"])
    cursor = conn.execute(
        "INSERT INTO anchors_memory_chunk "
        "(drawer_id, relative_path, start_line, end_line, language, index_generation) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (drawer_id, relative_path, start_line, end_line, language, index_generation),
    )
    return int(cursor.lastrowid)


def memory_anchors_for_symbol(
    conn: sqlite3.Connection, symbol_id: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT anchor_id, drawer_id, wing, room, created_by, confidence, created_at "
        "FROM anchors_symbol_memory WHERE symbol_id = ? ORDER BY anchor_id ASC",
        (symbol_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# -----------------------------------------------------------------------------
# change_log + dirty_files (v2)
# -----------------------------------------------------------------------------


def insert_change_log(
    conn: sqlite3.Connection,
    *,
    relative_path: str,
    change_type: str,
    source: str,
    tool: str | None = None,
    agent: str | None = None,
    conversation_id: str | None = None,
    tool_use_id: str | None = None,
    ts: str | None = None,
) -> int:
    if ts is None:
        cursor = conn.execute(
            "INSERT INTO change_log "
            "(relative_path, change_type, tool, agent, conversation_id, "
            "tool_use_id, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (relative_path, change_type, tool, agent, conversation_id,
             tool_use_id, source),
        )
    else:
        cursor = conn.execute(
            "INSERT INTO change_log "
            "(ts, relative_path, change_type, tool, agent, conversation_id, "
            "tool_use_id, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, relative_path, change_type, tool, agent, conversation_id,
             tool_use_id, source),
        )
    return int(cursor.lastrowid)


def upsert_dirty_file(conn: sqlite3.Connection, relative_path: str) -> None:
    conn.execute(
        "INSERT INTO dirty_files (relative_path) VALUES (?) "
        "ON CONFLICT(relative_path) DO UPDATE SET "
        "last_dirty_at = datetime('now')",
        (relative_path,),
    )


def dirty_file_paths(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT relative_path FROM dirty_files ORDER BY first_dirty_at ASC"
    ).fetchall()
    return [str(r["relative_path"]) for r in rows]


def clear_dirty_file(conn: sqlite3.Connection, relative_path: str) -> None:
    conn.execute(
        "DELETE FROM dirty_files WHERE relative_path = ?", (relative_path,)
    )


def mark_reindexed(conn: sqlite3.Connection, relative_path: str) -> int:
    cursor = conn.execute(
        "UPDATE change_log SET reindex_state = 'reindexed' "
        "WHERE relative_path = ? AND reindex_state = 'pending'",
        (relative_path,),
    )
    return int(cursor.rowcount or 0)


def changes_for_conversation(
    conn: sqlite3.Connection, conversation_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT change_id, ts, relative_path, change_type, tool, agent, "
        "conversation_id, tool_use_id, source, reindex_state "
        "FROM change_log WHERE conversation_id = ? "
        "ORDER BY change_id DESC LIMIT ?",
        (conversation_id, int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


# -----------------------------------------------------------------------------
# meta
# -----------------------------------------------------------------------------


def meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value, updated_at) VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
        "updated_at = datetime('now')",
        (key, value),
    )


# -----------------------------------------------------------------------------
# internal helpers
# -----------------------------------------------------------------------------


def _as_symbol(row: Any) -> SymbolRow | None:
    if row is None:
        return None
    return SymbolRow(
        symbol_id=int(row["symbol_id"]),
        name_path=str(row["name_path"]),
        relative_path=str(row["relative_path"]),
        kind=int(row["kind"]),
        tombstoned_at=row["tombstoned_at"],
    )


def _as_history(row: Any) -> HistoryRow:
    return HistoryRow(
        history_id=int(row["history_id"]),
        symbol_id=int(row["symbol_id"]),
        at_time=str(row["at_time"]),
        old_name_path=row["old_name_path"],
        new_name_path=row["new_name_path"],
        old_path=row["old_path"],
        new_path=row["new_path"],
        source=str(row["source"]),
    )

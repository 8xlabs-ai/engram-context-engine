from __future__ import annotations

import sqlite3
from importlib.resources import files
from pathlib import Path

META_SEEDS: tuple[tuple[str, str], ...] = (
    ("mempalace_wal_cursor", "0"),
    ("last_reconcile_at", "1970-01-01T00:00:00Z"),
    ("claude_context_index_generation", "0"),
)


def schema_sql() -> str:
    return files("engram.link").joinpath("schema.sql").read_text(encoding="utf-8")


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
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

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from engram.cli import main
from engram.config import Config
from engram.link.store import init_db

EXPECTED_TABLES = {
    "symbols",
    "anchors_symbol_memory",
    "anchors_symbol_chunk",
    "anchors_memory_chunk",
    "symbol_history",
    "meta",
}
EXPECTED_UNIQUE_PARTIAL = "idx_symbols_current_identity"
EXPECTED_UNIQUE_ANCHOR_INDICES = {
    "idx_asm_identity",
    "idx_asc_identity",
    "idx_amc_identity",
}
EXPECTED_FK_EDGES = {
    ("anchors_symbol_memory", "symbols"),
    ("anchors_symbol_chunk", "symbols"),
    ("symbol_history", "symbols"),
}


def test_init_db_creates_schema(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    conn = init_db(db)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert EXPECTED_TABLES.issubset(tables)

        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert user_version == 1

        indices = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert EXPECTED_UNIQUE_PARTIAL in indices
        assert EXPECTED_UNIQUE_ANCHOR_INDICES.issubset(indices)

        seeded_keys = {
            row[0] for row in conn.execute("SELECT key FROM meta").fetchall()
        }
        assert {
            "mempalace_wal_cursor",
            "last_reconcile_at",
            "claude_context_index_generation",
        }.issubset(seeded_keys)
    finally:
        conn.close()


def test_unique_partial_index_forbids_live_duplicate(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    conn = init_db(db)
    try:
        conn.execute(
            "INSERT INTO symbols (name_path, relative_path, kind) VALUES (?, ?, ?)",
            ("Foo/process", "src/foo.py", 12),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO symbols (name_path, relative_path, kind) VALUES (?, ?, ?)",
                ("Foo/process", "src/foo.py", 12),
            )
        # Tombstoned row + live row for the same identity is allowed.
        conn.execute(
            "UPDATE symbols SET tombstoned_at = datetime('now') "
            "WHERE name_path = 'Foo/process' AND relative_path = 'src/foo.py'"
        )
        conn.execute(
            "INSERT INTO symbols (name_path, relative_path, kind) VALUES (?, ?, ?)",
            ("Foo/process", "src/foo.py", 12),
        )
    finally:
        conn.close()


def test_foreign_keys_configured(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    conn = init_db(db)
    try:
        discovered: set[tuple[str, str]] = set()
        for (table,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall():
            for row in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall():
                discovered.add((table, row[2]))
        assert EXPECTED_FK_EDGES.issubset(discovered)
    finally:
        conn.close()


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    init_db(db).close()

    conn = sqlite3.connect(db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM meta WHERE key = 'mempalace_wal_cursor'"
        ).fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_cli_init_writes_config_and_db(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "init",
            "--workspace",
            str(tmp_path),
            "--embedding-provider",
            "Ollama",
            "--skip-prereq-check",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip())
    assert payload["embedding_provider"] == "Ollama"

    cfg = Config.load(tmp_path / ".engram/config.yaml")
    assert cfg.version == 1
    assert cfg.workspace.name == tmp_path.name
    assert cfg.upstreams.claude_context.embedding_provider == "Ollama"

    assert (tmp_path / ".engram/anchors.sqlite").exists()


def test_cli_init_refuses_overwrite_without_force(tmp_path: Path) -> None:
    runner = CliRunner()
    args = [
        "init",
        "--workspace",
        str(tmp_path),
        "--embedding-provider",
        "Ollama",
        "--skip-prereq-check",
    ]
    assert runner.invoke(main, args).exit_code == 0
    second = runner.invoke(main, args)
    assert second.exit_code == 1
    assert "already exists" in second.output

    third = runner.invoke(main, args + ["--force"])
    assert third.exit_code == 0, third.output

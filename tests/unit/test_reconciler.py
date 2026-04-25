from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from click.testing import CliRunner

from engram.cli import main as cli_main
from engram.link.store import (
    init_db,
    open_db,
    tombstone_symbol,
    upsert_anchor_symbol_memory,
    upsert_symbol,
)
from engram.workers.reconciler import reconcile


def _init_workspace(tmp_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(
        cli_main,
        [
            "init",
            "--workspace",
            str(tmp_path),
            "--embedding-provider",
            "Ollama",
            "--skip-prereq-check",
        ],
    )


def test_reconciler_dry_run_preserves_db_hash(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    conn = init_db(db)
    try:
        sid = upsert_symbol(
            conn, name_path="Foo/process", relative_path="src/foo.py", kind=12
        )
        upsert_anchor_symbol_memory(
            conn,
            symbol_id=sid,
            drawer_id="D1",
            wing="w",
            room="r",
            created_by="explicit",
        )
    finally:
        conn.close()

    async def drawer_lookup(_drawer_id):
        return None  # all drawers missing → reconciler would delete them

    before = _sha(db)

    async def go():
        return await reconcile(
            db, scope="all", dry_run=True, drawer_lookup=drawer_lookup
        )

    report = asyncio.run(go())
    after = _sha(db)
    assert before == after
    # Report still tallies what would have changed.
    assert report.scanned["memories"] == 1


def test_reconciler_live_run_removes_dangling_memory_anchor(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    conn = init_db(db)
    try:
        sid = upsert_symbol(
            conn, name_path="Foo/process", relative_path="src/foo.py", kind=12
        )
        upsert_anchor_symbol_memory(
            conn,
            symbol_id=sid,
            drawer_id="D-gone",
            wing="w",
            room="r",
            created_by="explicit",
        )
    finally:
        conn.close()

    async def drawer_lookup(_drawer_id):
        return None

    async def go():
        return await reconcile(
            db, scope="memories", dry_run=False, drawer_lookup=drawer_lookup
        )

    report = asyncio.run(go())
    assert report.changed["anchors"] == 1
    assert report.changed["tombstones"] == 1
    conn = open_db(db)
    try:
        rows = conn.execute(
            "SELECT COUNT(*) AS n FROM anchors_symbol_memory"
        ).fetchone()
        assert rows["n"] == 0
    finally:
        conn.close()


def test_reconciler_chunks_scope_drops_anchors_for_tombstoned_symbols(
    tmp_path: Path,
) -> None:
    db = tmp_path / "anchors.sqlite"
    conn = init_db(db)
    try:
        sid = upsert_symbol(
            conn, name_path="Foo/process", relative_path="src/foo.py", kind=12
        )
        conn.execute(
            "INSERT INTO anchors_symbol_chunk "
            "(symbol_id, relative_path, start_line, end_line, language, index_generation) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, "src/foo.py", 1, 10, "python", 0),
        )
        tombstone_symbol(conn, sid)
    finally:
        conn.close()

    async def go():
        return await reconcile(db, scope="chunks", dry_run=False)

    report = asyncio.run(go())
    assert report.changed["anchors"] == 1
    conn = open_db(db)
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM anchors_symbol_chunk"
        ).fetchone()["n"]
        assert n == 0
    finally:
        conn.close()


def test_cli_reconcile_dry_run(tmp_path: Path) -> None:
    _init_workspace(tmp_path)
    db = tmp_path / ".engram/anchors.sqlite"
    before = _sha(db)
    runner = CliRunner()
    result = runner.invoke(
        cli_main,
        [
            "reconcile",
            "--workspace",
            str(tmp_path),
            "--scope",
            "all",
            "--dry-run",
            "--skip-upstreams",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip())
    assert "changed" in payload
    after = _sha(db)
    assert before == after


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

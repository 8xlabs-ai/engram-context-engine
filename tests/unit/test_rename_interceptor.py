from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from engram.link.store import get_symbol, history_for, init_db, open_db, upsert_symbol
from engram.tools.registry import ToolRegistry
from engram.tools.write_hooks import (
    _rename_preview,
    make_rename_interceptor,
    make_safe_delete_interceptor,
)
from engram.upstream.client import UpstreamSpec
from engram.upstream.supervisor import Supervisor

REPO_SRC = Path(__file__).parent.parent.parent / "src"
FIX = Path(__file__).parent.parent / "fixtures"


def _serena_spec(extra_env: dict | None = None) -> UpstreamSpec:
    env = {**os.environ, "PYTHONPATH": str(REPO_SRC)}
    if extra_env:
        env.update(extra_env)
    return UpstreamSpec(
        name="serena",
        command=[sys.executable, str(FIX / "fake_serena.py")],
        env=env,
        namespace="code",
    )


def _mempalace_spec(drawers: list[dict], log_file: Path) -> UpstreamSpec:
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_SRC),
        "FAKE_MEMPALACE_SEED": json.dumps(drawers),
        "FAKE_MEMPALACE_LOG": str(log_file),
    }
    return UpstreamSpec(
        name="mempalace",
        command=[sys.executable, str(FIX / "fake_mempalace.py")],
        env=env,
        namespace="mem",
    )


def test_rename_preview_last_segment() -> None:
    assert _rename_preview("Foo/process", "run") == "Foo/run"
    assert _rename_preview("top", "root") == "root"


def test_rename_interceptor_happy_path(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    conn = init_db(db)
    try:
        upsert_symbol(
            conn, name_path="Foo/process", relative_path="src/foo.py", kind=12
        )
    finally:
        conn.close()

    log_file = tmp_path / "mem.log"

    async def run() -> None:
        specs = [
            _serena_spec(),
            _mempalace_spec(drawers=[], log_file=log_file),
        ]
        async with Supervisor(specs=specs) as sup:
            serena = sup.get("serena")
            assert serena is not None
            handler = make_rename_interceptor(
                db, serena, lambda: sup.get("mempalace")
            )
            resp = await handler(
                {
                    "name_path": "Foo/process",
                    "relative_path": "src/foo.py",
                    "new_name": "run",
                }
            )
            assert "result" in resp, resp
            assert resp["meta"]["upstream"] == "serena"
            assert resp["meta"]["path_used"] == "B"

    asyncio.run(run())

    # Symbol renamed in DB
    conn = open_db(db)
    try:
        sym = get_symbol(conn, "Foo/run", "src/foo.py")
        assert sym is not None
        hist = history_for(conn, sym.symbol_id)
        assert hist[-1].source == "engram-rename"
        assert hist[-1].old_name_path == "Foo/process"
        assert hist[-1].new_name_path == "Foo/run"
    finally:
        conn.close()

    # KG tools were invoked by the interceptor
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    ops = [json.loads(l)["op"] for l in lines]
    assert "mempalace_kg_add" in ops
    assert "mempalace_kg_invalidate" in ops


def test_rename_interceptor_rolls_back_on_upstream_failure(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    conn = init_db(db)
    try:
        upsert_symbol(
            conn, name_path="Foo/process", relative_path="src/foo.py", kind=12
        )
    finally:
        conn.close()

    log_file = tmp_path / "mem.log"

    async def run():
        specs = [
            _serena_spec({"FAKE_SERENA_FAIL_ON": "rename_symbol"}),
            _mempalace_spec(drawers=[], log_file=log_file),
        ]
        async with Supervisor(specs=specs) as sup:
            serena = sup.get("serena")
            handler = make_rename_interceptor(
                db, serena, lambda: sup.get("mempalace")
            )
            return await handler(
                {
                    "name_path": "Foo/process",
                    "relative_path": "src/foo.py",
                    "new_name": "run",
                }
            )

    resp = asyncio.run(run())
    assert resp["error"]["code"] == "consistency-state-hint"

    conn = open_db(db)
    try:
        sym = get_symbol(conn, "Foo/process", "src/foo.py")
        assert sym is not None  # still there after rollback
        sym_new = get_symbol(conn, "Foo/run", "src/foo.py")
        assert sym_new is None
    finally:
        conn.close()

    # KG helpers not invoked when rename failed
    if log_file.exists():
        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
        ops = {json.loads(l)["op"] for l in lines}
        assert "mempalace_kg_add" not in ops


def test_safe_delete_interceptor_tombstones_symbol(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    conn = init_db(db)
    try:
        sid = upsert_symbol(
            conn, name_path="Foo/process", relative_path="src/foo.py", kind=12
        )
    finally:
        conn.close()

    log_file = tmp_path / "mem.log"

    async def run():
        specs = [
            _serena_spec(),
            _mempalace_spec(drawers=[], log_file=log_file),
        ]
        async with Supervisor(specs=specs) as sup:
            serena = sup.get("serena")
            handler = make_safe_delete_interceptor(
                db, serena, lambda: sup.get("mempalace")
            )
            return await handler(
                {"name_path": "Foo/process", "relative_path": "src/foo.py"}
            )

    resp = asyncio.run(run())
    assert "result" in resp

    conn = open_db(db)
    try:
        # Live row is gone
        assert get_symbol(conn, "Foo/process", "src/foo.py") is None
        hist = history_for(conn, sid)
        assert hist[-1].source == "engram-delete"
    finally:
        conn.close()

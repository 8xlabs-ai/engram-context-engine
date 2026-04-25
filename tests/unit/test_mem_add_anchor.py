from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from engram.link.store import init_db, open_db
from engram.tools.mem_add_anchor import make_mem_add_handler
from engram.upstream.client import UpstreamSpec
from engram.upstream.supervisor import Supervisor

REPO_SRC = Path(__file__).parent.parent.parent / "src"
FIX = Path(__file__).parent.parent / "fixtures"


def _mempalace_spec(log_file: Path) -> UpstreamSpec:
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_SRC),
        "FAKE_MEMPALACE_LOG": str(log_file),
        "FAKE_MEMPALACE_SEED": "[]",
    }
    return UpstreamSpec(
        name="mempalace",
        command=[sys.executable, str(FIX / "fake_mempalace.py")],
        env=env,
        namespace="mem",
    )


def test_mem_add_without_anchor_fields_is_plain_passthrough(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    log_file = tmp_path / "mem.log"

    async def run():
        async with Supervisor(specs=[_mempalace_spec(log_file)]) as sup:
            client = sup.get("mempalace")
            handler = make_mem_add_handler(db, client)
            return await handler(
                {
                    "wing": "engram",
                    "room": "backend",
                    "content": "hello world",
                    "drawer_id": "D100",
                }
            )

    resp = asyncio.run(run())
    assert "result" in resp
    assert resp["result"]["drawer_id"] == "D100"

    # No anchor rows created
    conn = open_db(db)
    try:
        n = conn.execute("SELECT COUNT(*) FROM anchors_symbol_memory").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_mem_add_with_anchor_fields_creates_anchor(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    log_file = tmp_path / "mem.log"

    async def run():
        async with Supervisor(specs=[_mempalace_spec(log_file)]) as sup:
            client = sup.get("mempalace")
            handler = make_mem_add_handler(db, client)
            return await handler(
                {
                    "wing": "engram",
                    "room": "backend",
                    "content": "hello",
                    "drawer_id": "D200",
                    "anchor_symbol_name_path": "Foo/process",
                    "anchor_relative_path": "src/foo.py",
                }
            )

    resp = asyncio.run(run())
    assert "result" in resp
    assert resp["meta"].get("anchor_id") is not None
    assert resp["result"]["drawer_id"] == "D200"

    conn = open_db(db)
    try:
        # Exactly one anchors_symbol_memory row that points at D200
        rows = conn.execute(
            "SELECT drawer_id, wing, room, created_by FROM anchors_symbol_memory"
        ).fetchall()
        assert len(rows) == 1
        r = dict(rows[0])
        assert r["drawer_id"] == "D200"
        assert r["wing"] == "engram"
        assert r["room"] == "backend"
        assert r["created_by"] == "mem.add-fast-path"
    finally:
        conn.close()

    # The upstream tool call was logged (i.e. it actually reached mempalace)
    ops = [json.loads(l)["op"] for l in log_file.read_text().strip().splitlines()]
    assert "mempalace_add_drawer" in ops


def test_mem_add_strips_anchor_fields_before_forwarding(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    log_file = tmp_path / "mem.log"

    async def run():
        async with Supervisor(specs=[_mempalace_spec(log_file)]) as sup:
            client = sup.get("mempalace")
            handler = make_mem_add_handler(db, client)
            await handler(
                {
                    "wing": "w",
                    "room": "r",
                    "content": "c",
                    "drawer_id": "D1",
                    "anchor_symbol_name_path": "Foo",
                    "anchor_relative_path": "src/x.py",
                }
            )

    asyncio.run(run())
    lines = log_file.read_text().strip().splitlines()
    add_call = next(
        json.loads(l) for l in lines if json.loads(l)["op"] == "mempalace_add_drawer"
    )
    assert "anchor_symbol_name_path" not in add_call["payload"]
    assert "anchor_relative_path" not in add_call["payload"]

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from engram.link.store import init_db, open_db
from engram.tools.vec_enrich import make_vec_search_handler
from engram.upstream.client import UpstreamSpec
from engram.upstream.supervisor import Supervisor

REPO_SRC = Path(__file__).parent.parent.parent / "src"
FIX = Path(__file__).parent.parent / "fixtures"


def _cc_spec(chunks: list[dict]) -> UpstreamSpec:
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_SRC),
        "FAKE_CC_CHUNKS": json.dumps(chunks),
    }
    return UpstreamSpec(
        name="claude_context",
        command=[sys.executable, str(FIX / "fake_cc.py")],
        env=env,
        namespace="vec",
    )


def _serena_spec(overview: list[dict]) -> UpstreamSpec:
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_SRC),
        "FAKE_SERENA_OVERVIEW": json.dumps(overview),
    }
    return UpstreamSpec(
        name="serena",
        command=[sys.executable, str(FIX / "fake_serena.py")],
        env=env,
        namespace="code",
    )


def test_enriches_chunk_via_serena_overview(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()

    chunks = [
        {"relativePath": "src/foo.py", "startLine": 10, "endLine": 12, "content": "..."}
    ]
    overview = [
        {"name_path": "Foo/process", "start_line": 8, "end_line": 20, "kind": 12}
    ]

    async def run():
        async with Supervisor(specs=[_cc_spec(chunks), _serena_spec(overview)]) as sup:
            handler = make_vec_search_handler(
                db, sup.get("claude_context"), lambda: sup.get("serena")
            )
            return await handler({"query": "parse json"})

    resp = asyncio.run(run())
    assert "result" in resp
    enriched = resp["result"]["results"]
    assert len(enriched) == 1
    enc = enriched[0]["enclosing_symbol"]
    assert enc["name_path"] == "Foo/process"
    assert enc["source"] == "serena_live"


def test_enrich_uses_anchor_cache_when_present(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()

    conn = open_db(db)
    try:
        conn.execute(
            "INSERT INTO symbols (name_path, relative_path, kind) VALUES (?, ?, ?)",
            ("Bar/run", "src/bar.py", 12),
        )
        sid = conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]
        conn.execute(
            "INSERT INTO anchors_symbol_chunk "
            "(symbol_id, relative_path, start_line, end_line, language, index_generation) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, "src/bar.py", 5, 30, "python", 0),
        )
    finally:
        conn.close()

    chunks = [
        {"relativePath": "src/bar.py", "startLine": 10, "endLine": 12, "content": "..."}
    ]

    async def run():
        async with Supervisor(specs=[_cc_spec(chunks), _serena_spec([])]) as sup:
            handler = make_vec_search_handler(
                db, sup.get("claude_context"), lambda: sup.get("serena")
            )
            return await handler({"query": "x"})

    resp = asyncio.run(run())
    enc = resp["result"]["results"][0]["enclosing_symbol"]
    assert enc["name_path"] == "Bar/run"
    assert enc["source"] == "anchor_cache"


def test_chunk_without_match_has_null_enclosing_symbol(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    chunks = [{"relativePath": "src/unknown.py", "startLine": 1, "endLine": 1}]

    async def run():
        async with Supervisor(specs=[_cc_spec(chunks), _serena_spec([])]) as sup:
            handler = make_vec_search_handler(
                db, sup.get("claude_context"), lambda: sup.get("serena")
            )
            return await handler({"query": "x"})

    resp = asyncio.run(run())
    assert resp["result"]["results"][0]["enclosing_symbol"] is None

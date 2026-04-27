from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from engram.tools.engram_ns import register_engram_tools
from engram.tools.registry import ToolRegistry
from engram.upstream.client import UpstreamSpec
from engram.upstream.supervisor import Supervisor

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_upstream.py"


def _spec(name: str, prefix: str) -> UpstreamSpec:
    return UpstreamSpec(
        name=name,
        command=[sys.executable, str(FAKE), prefix],
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).parent.parent.parent / "src"),
        },
        namespace={"serena": "code", "mempalace": "mem", "claude_context": "vec"}[name],
    )


def test_health_status_ok_when_all_upstreams_up(tmp_path: Path) -> None:
    async def run() -> None:
        specs = [
            _spec("serena", "get_current_config"),
            _spec("mempalace", "mempalace_status"),
            _spec("claude_context", "get_indexing_status"),
        ]
        async with Supervisor(specs=specs) as sup:
            assert len(sup.clients) == 3
            registry = ToolRegistry()
            register_engram_tools(registry, tmp_path / "anchors.sqlite", supervisor=sup)
            spec = registry.get("engram.health")
            payload = await spec.handler({})  # type: ignore[union-attr]
            assert payload["result"]["status"] == "ok"
            for name in ("serena", "mempalace", "claude_context"):
                assert payload["result"]["upstreams"][name]["ok"] is True

    asyncio.run(run())


def test_health_status_degraded_when_one_upstream_down(tmp_path: Path) -> None:
    async def run() -> None:
        specs = [
            _spec("serena", "get_current_config"),
            UpstreamSpec(
                name="mempalace",
                command=[sys.executable, "-c", "import sys; sys.exit(7)"],
                namespace="mem",
            ),
            _spec("claude_context", "get_indexing_status"),
        ]
        async with Supervisor(specs=specs) as sup:
            assert "mempalace" not in sup.clients
            registry = ToolRegistry()
            register_engram_tools(registry, tmp_path / "anchors.sqlite", supervisor=sup)
            spec = registry.get("engram.health")
            payload = await spec.handler({})  # type: ignore[union-attr]
            assert payload["result"]["status"] == "degraded"
            assert payload["result"]["upstreams"]["serena"]["ok"] is True
            assert payload["result"]["upstreams"]["mempalace"]["ok"] is False
            assert payload["result"]["upstreams"]["claude_context"]["ok"] is True

    asyncio.run(run())


def test_health_status_down_when_no_supervisor(tmp_path: Path) -> None:
    async def run() -> None:
        registry = ToolRegistry()
        register_engram_tools(registry, tmp_path / "anchors.sqlite", supervisor=None)
        spec = registry.get("engram.health")
        payload = await spec.handler({})  # type: ignore[union-attr]
        assert payload["result"]["status"] == "down"

    asyncio.run(run())


def test_health_reports_wal_lag_after_tailer_drives_event(tmp_path: Path) -> None:
    import json

    from engram.link.store import init_db
    from engram.workers.wal_tailer import WalTailer

    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    wal = tmp_path / "wal" / "write_log.jsonl"
    wal.parent.mkdir(parents=True, exist_ok=True)
    with wal.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"op": "add_drawer", "drawer_id": "D0"}) + "\n")

    async def run() -> None:
        tailer = WalTailer(wal_path=wal, db_path=db, poll_interval_s=0.01)
        await tailer._tick_once()

        registry = ToolRegistry()
        register_engram_tools(registry, db, supervisor=None)
        spec = registry.get("engram.health")
        payload = await spec.handler({})  # type: ignore[union-attr]
        lag = payload["result"]["upstreams"]["mempalace"].get("wal_lag_seconds")
        assert isinstance(lag, (int, float))
        assert 0 <= lag < 5

    asyncio.run(run())

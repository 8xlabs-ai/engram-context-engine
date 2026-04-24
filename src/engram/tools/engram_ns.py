from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from engram import __version__
from engram.link.store import open_db
from engram.tools.envelope import latency_meter, success
from engram.tools.registry import ToolRegistry, ToolSpec
from engram.upstream.client import UpstreamClient
from engram.upstream.supervisor import Supervisor

log = logging.getLogger("engram.health")

HEALTH_DESCRIPTION = (
    "Report Engram and upstream liveness plus anchor-store counts.\n"
    "Use when you need a one-shot status probe before making a compound call."
)

# Lightweight probes per upstream — each is a tool on the upstream that returns
# fast and does not mutate state. Picked from docs 01–03.
PROBE_TOOL = {
    "serena": "get_current_config",
    "mempalace": "mempalace_status",
    "claude_context": "get_indexing_status",
}


def register_engram_tools(
    registry: ToolRegistry,
    anchor_db_path: Path,
    supervisor: Supervisor | None = None,
) -> None:
    async def health_handler(_args: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            upstreams = await _probe_all(supervisor)
            status = _roll_up_status(upstreams)
            result: dict[str, Any] = {
                "status": status,
                "engram_version": __version__,
                "upstreams": upstreams,
                "anchor_store": _anchor_counts(anchor_db_path),
            }
        return success(result, meta_extra={"latency_ms": m["latency_ms"]})

    registry.register(
        ToolSpec(
            name="engram.health",
            description=HEALTH_DESCRIPTION,
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=health_handler,
        )
    )


async def _probe_all(supervisor: Supervisor | None) -> dict[str, dict[str, Any]]:
    upstreams: dict[str, dict[str, Any]] = {
        name: {"ok": False, "reason": "not connected"}
        for name in PROBE_TOOL
    }
    if supervisor is None:
        return upstreams
    for name, probe in PROBE_TOOL.items():
        client = supervisor.get(name)
        if client is None:
            continue
        upstreams[name] = await _probe_one(client, probe)
    return upstreams


async def _probe_one(client: UpstreamClient, probe_tool: str) -> dict[str, Any]:
    has_tool = any(t.name == probe_tool for t in client.tools)
    if not has_tool:
        # Upstream is connected but exposes no canonical probe; treat as ok
        # since list_tools already succeeded during connect.
        return {"ok": True, "latency_ms": 0.0, "probe": None}
    start = time.perf_counter()
    try:
        result = await client.call_tool(probe_tool, {})
    except Exception as exc:  # noqa: BLE001
        log.warning("probe %s on %s failed: %s", probe_tool, client.spec.name, exc)
        return {"ok": False, "reason": str(exc), "probe": probe_tool}
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    if result.isError:
        return {"ok": False, "reason": "probe returned error", "probe": probe_tool}
    return {"ok": True, "latency_ms": latency_ms, "probe": probe_tool}


def _roll_up_status(upstreams: dict[str, dict[str, Any]]) -> str:
    oks = [u["ok"] for u in upstreams.values()]
    if all(oks):
        return "ok"
    if any(oks):
        return "degraded"
    return "down"


def _anchor_counts(db_path: Path) -> dict[str, int]:
    if not db_path.exists():
        return {"symbols": 0, "anchors_symbol_memory": 0, "anchors_symbol_chunk": 0}
    conn = open_db(db_path)
    try:
        return {
            "symbols": _count(conn, "symbols"),
            "anchors_symbol_memory": _count(conn, "anchors_symbol_memory"),
            "anchors_symbol_chunk": _count(conn, "anchors_symbol_chunk"),
        }
    finally:
        conn.close()


def _count(conn: Any, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

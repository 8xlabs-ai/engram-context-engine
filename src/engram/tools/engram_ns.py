from __future__ import annotations

from pathlib import Path
from typing import Any

from engram import __version__
from engram.link.store import open_db
from engram.tools.envelope import latency_meter, success
from engram.tools.registry import ToolRegistry, ToolSpec

HEALTH_DESCRIPTION = (
    "Report Engram and upstream liveness plus anchor-store counts. "
    "Use when you need a one-shot status probe before making a compound call."
)


def register_engram_tools(registry: ToolRegistry, anchor_db_path: Path) -> None:
    async def health_handler(_args: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            result: dict[str, Any] = {
                "status": "ok",
                "engram_version": __version__,
                "upstreams": {
                    "serena": {"ok": False, "reason": "proxy not wired (M0 1.4)"},
                    "mempalace": {"ok": False, "reason": "proxy not wired (M0 1.4)"},
                    "claude_context": {"ok": False, "reason": "proxy not wired (M0 1.4)"},
                },
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

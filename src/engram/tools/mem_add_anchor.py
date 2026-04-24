"""mem.add fast-path: optional anchor_symbol_name_path/anchor_relative_path.

When callers supply the two optional anchor fields on mem.add, Engram inserts
one `anchors_symbol_memory` row after MemPalace confirms the drawer write —
same semantics as calling `engram.anchor_memory_to_symbol` afterwards, minus
an extra MCP round trip.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from engram.link.store import open_db, upsert_anchor_symbol_memory, upsert_symbol
from engram.tools.envelope import failure, latency_meter, success
from engram.tools.registry import ToolHandler
from engram.upstream.client import UpstreamClient

log = logging.getLogger("engram.mem_add_anchor")

ANCHOR_KEYS = ("anchor_symbol_name_path", "anchor_relative_path")


def make_mem_add_handler(
    db_path: Path, mempalace_client: UpstreamClient
) -> ToolHandler:
    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            args = dict(arguments)
            anchor_name = args.pop("anchor_symbol_name_path", None)
            anchor_path = args.pop("anchor_relative_path", None)

            try:
                result = await mempalace_client.call_tool(
                    "mempalace_add_drawer", args
                )
            except Exception as exc:
                return failure(
                    "upstream-unavailable",
                    f"mempalace_add_drawer failed: {exc}",
                    meta_extra={"latency_ms": m["latency_ms"], "upstream": "mempalace"},
                )
            if result.isError:
                return failure(
                    "upstream-unavailable",
                    "mempalace_add_drawer returned error",
                    details=_structured(result),
                    meta_extra={"latency_ms": m["latency_ms"], "upstream": "mempalace"},
                )

            drawer_payload = _structured(result) or {}
            drawer_id = drawer_payload.get("drawer_id") if isinstance(drawer_payload, dict) else None

            anchor_id: int | None = None
            if anchor_name and anchor_path and isinstance(drawer_id, str):
                conn = open_db(db_path)
                try:
                    symbol_id = upsert_symbol(
                        conn,
                        name_path=str(anchor_name),
                        relative_path=str(anchor_path),
                        kind=0,
                    )
                    anchor_id = upsert_anchor_symbol_memory(
                        conn,
                        symbol_id=symbol_id,
                        drawer_id=drawer_id,
                        wing=str(arguments.get("wing", "")),
                        room=str(arguments.get("room", "")),
                        created_by="mem.add-fast-path",
                    )
                finally:
                    conn.close()

        meta_extra: dict[str, Any] = {
            "latency_ms": m["latency_ms"],
            "upstream": "mempalace",
        }
        if anchor_id is not None:
            meta_extra["anchor_id"] = anchor_id
        return success(drawer_payload, meta_extra=meta_extra)

    return handler


MEM_ADD_DESCRIPTION = (
    "Write a verbatim drawer to MemPalace, optionally anchoring to a code symbol.\n"
    "Prefer this over mem.add + engram.anchor_memory_to_symbol when the anchor is known."
)

MEM_ADD_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "wing": {"type": "string"},
        "room": {"type": "string"},
        "content": {"type": "string"},
        "anchor_symbol_name_path": {"type": "string"},
        "anchor_relative_path": {"type": "string"},
    },
    "required": ["wing", "room", "content"],
    "additionalProperties": True,
}


def _structured(result: Any) -> Any:
    if getattr(result, "structuredContent", None):
        return dict(result.structuredContent)
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is None:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return None

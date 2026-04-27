"""MCP tools for file-change notification and conversation-scoped queries.

`engram.notify_file_changed` is the canonical way for any caller (the
JSONL inbox tailer, tests, non-Claude clients) to tell Engram "this file
changed". It publishes EVENT_FILE_REPLACED on the in-process HookBus;
the change_log subscriber writes the row and marks the file dirty.

`engram.changes_in_conversation` reads the resulting `change_log` rows
filtered by conversation_id.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from engram.events import EVENT_FILE_REPLACED, HookBus
from engram.link.store import changes_for_conversation, open_db
from engram.tools.envelope import failure, latency_meter, success
from engram.tools.registry import ToolRegistry, ToolSpec

log = logging.getLogger("engram.tools.notify")

NOTIFY_DESCRIPTION = (
    "Record that a file changed (Engram, Claude Code, or any other agent).\n"
    "Use to keep anchors and reindex state fresh; safe to call repeatedly."
)

CHANGES_IN_CONVERSATION_DESCRIPTION = (
    "List file changes recorded for a given Claude Code conversation_id.\n"
    "Use to answer 'what code did we touch in this session?'."
)

ALLOWED_CHANGE_TYPES = {"edit", "write", "delete", "notebook_edit"}
ALLOWED_SOURCES = {"engram_write_hook", "claude_code_hook", "manual"}


NotifyHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def make_notify_handler(bus: HookBus) -> NotifyHandler:
    """Return an async callable that publishes a change to the bus.

    The same handler powers the MCP tool and the JSONL inbox tailer, so
    both ingest paths converge on identical state.
    """

    async def handler(payload: dict[str, Any]) -> dict[str, Any]:
        relative_path = payload.get("relative_path")
        if not isinstance(relative_path, str) or not relative_path:
            return {"accepted": False, "reason": "relative_path required"}

        change_type = str(payload.get("change_type") or "edit")
        if change_type not in ALLOWED_CHANGE_TYPES:
            return {
                "accepted": False,
                "reason": f"change_type must be one of {sorted(ALLOWED_CHANGE_TYPES)}",
            }
        source = str(payload.get("source") or "manual")
        if source not in ALLOWED_SOURCES:
            return {
                "accepted": False,
                "reason": f"source must be one of {sorted(ALLOWED_SOURCES)}",
            }

        ts = payload.get("ts")
        if ts is None:
            ts = time.time()

        await bus.publish(
            EVENT_FILE_REPLACED,
            {
                "relative_path": relative_path,
                "change_type": change_type,
                "source": source,
                "tool": payload.get("tool"),
                "agent": payload.get("agent"),
                "conversation_id": payload.get("conversation_id"),
                "tool_use_id": payload.get("tool_use_id"),
                "ts": ts,
            },
        )
        return {"accepted": True}

    return handler


def register_notify_tools(
    registry: ToolRegistry,
    anchor_db_path: Path,
    bus: HookBus,
) -> None:
    notify_handler = make_notify_handler(bus)

    async def notify_tool(args: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            result = await notify_handler(args)
            if not result.get("accepted"):
                return failure(
                    "invalid-input",
                    str(result.get("reason", "rejected")),
                    meta_extra={"latency_ms": m["latency_ms"]},
                )
        return success(result, meta_extra={"latency_ms": m["latency_ms"]})

    registry.register(
        ToolSpec(
            name="engram.notify_file_changed",
            description=NOTIFY_DESCRIPTION,
            input_schema={
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string"},
                    "change_type": {
                        "type": "string",
                        "enum": sorted(ALLOWED_CHANGE_TYPES),
                    },
                    "source": {
                        "type": "string",
                        "enum": sorted(ALLOWED_SOURCES),
                    },
                    "tool": {"type": "string"},
                    "agent": {"type": "string"},
                    "conversation_id": {"type": "string"},
                    "tool_use_id": {"type": "string"},
                    "ts": {"type": "number"},
                },
                "required": ["relative_path"],
                "additionalProperties": False,
            },
            handler=notify_tool,
        )
    )

    async def changes_tool(args: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            conversation_id = args.get("conversation_id")
            limit = int(args.get("limit", 50))
            if not isinstance(conversation_id, str) or not conversation_id:
                return failure(
                    "invalid-input",
                    "conversation_id required",
                    meta_extra={"latency_ms": m["latency_ms"]},
                )
            if not anchor_db_path.exists():
                return success(
                    {"conversation_id": conversation_id, "changes": []},
                    meta_extra={"latency_ms": m["latency_ms"]},
                )
            conn = open_db(anchor_db_path)
            try:
                rows = changes_for_conversation(conn, conversation_id, limit=limit)
            finally:
                conn.close()
        return success(
            {"conversation_id": conversation_id, "changes": rows},
            meta_extra={"latency_ms": m["latency_ms"]},
        )

    registry.register(
        ToolSpec(
            name="engram.changes_in_conversation",
            description=CHANGES_IN_CONVERSATION_DESCRIPTION,
            input_schema={
                "type": "object",
                "properties": {
                    "conversation_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": ["conversation_id"],
                "additionalProperties": False,
            },
            handler=changes_tool,
        )
    )

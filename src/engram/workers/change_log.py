"""HookBus subscriber that records every file change.

Listens to EVENT_FILE_REPLACED (published by Engram-internal write hooks
and by the JSONL inbox tailer that ingests Claude Code PostToolUse events).
On each event:

  1. Inserts a row into the `change_log` table.
  2. Marks the file dirty in `dirty_files` so the fast reconciler tick
     sweeps stale anchors against it on the next pass.
  3. For `change_type='delete'`, tombstones any matching live symbol row.
  4. Optional: writes a (conversation:X)-[edited]->(file:Y) fact to the
     KG via mempalace_kg_add — fire-and-forget; failures are logged.

LRU cache invalidation continues to flow through the existing subscriber
in `engram.router.cache.LRUCache.subscribe_to`. We do not duplicate it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from engram.events import EVENT_FILE_REPLACED, HookBus
from engram.link.store import (
    insert_change_log,
    open_db,
    tombstone_symbol,
    upsert_dirty_file,
)
from engram.upstream.client import UpstreamClient

log = logging.getLogger("engram.workers.change_log")


def attach_change_logger(
    bus: HookBus,
    db_path: Path,
    *,
    kg_client: UpstreamClient | None = None,
) -> None:
    """Subscribe a change-log handler to the bus."""

    async def handler(payload: dict[str, Any]) -> None:
        relative_path = payload.get("relative_path")
        if not isinstance(relative_path, str) or not relative_path:
            log.debug("change_log handler ignoring payload without relative_path")
            return

        change_type = str(payload.get("change_type") or "edit")
        source = str(payload.get("source") or "manual")
        tool = _opt_str(payload.get("tool"))
        agent = _opt_str(payload.get("agent"))
        conversation_id = _opt_str(payload.get("conversation_id"))
        tool_use_id = _opt_str(payload.get("tool_use_id"))

        conn = open_db(db_path)
        try:
            insert_change_log(
                conn,
                relative_path=relative_path,
                change_type=change_type,
                source=source,
                tool=tool,
                agent=agent,
                conversation_id=conversation_id,
                tool_use_id=tool_use_id,
            )
            upsert_dirty_file(conn, relative_path)
            if change_type == "delete":
                _tombstone_symbols_for(conn, relative_path)
        finally:
            conn.close()

        if conversation_id and kg_client is not None:
            await _mirror_to_kg(kg_client, conversation_id, relative_path)

    bus.subscribe(EVENT_FILE_REPLACED, handler)


def _opt_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _tombstone_symbols_for(conn: Any, relative_path: str) -> None:
    rows = conn.execute(
        "SELECT symbol_id FROM symbols "
        "WHERE relative_path = ? AND tombstoned_at IS NULL",
        (relative_path,),
    ).fetchall()
    for row in rows:
        tombstone_symbol(
            conn, int(row["symbol_id"]), source="file_deleted"
        )


async def _mirror_to_kg(
    client: UpstreamClient, conversation_id: str, relative_path: str
) -> None:
    try:
        await client.call_tool(
            "mempalace_kg_add",
            {
                "subject": f"conversation:{conversation_id}",
                "predicate": "edited",
                "object": f"file:{relative_path}",
            },
        )
    except Exception:  # noqa: BLE001
        log.exception("failed to mirror change to KG; ignoring")

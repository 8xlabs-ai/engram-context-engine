"""Tail Claude Code's PostToolUse JSONL inbox.

The Claude Code PostToolUse hook script appends one JSON line per
Edit/Write/NotebookEdit tool call to
`<workspace>/.engram/inbox/hook_events.jsonl`. This worker tails the
file, persists a byte-offset cursor in the `meta` table, and dispatches
each event to a notify handler that publishes EVENT_FILE_REPLACED.

Pattern mirrors `engram.workers.wal_tailer.WalTailer` — same partial-
line + rotation handling, same async loop shape.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engram.link.store import meta_get, meta_set, open_db

log = logging.getLogger("engram.hook_inbox")

META_CURSOR_KEY = "cc_hook_inbox_cursor"
META_LAST_EVENT_AT = "cc_hook_inbox_last_event_at"

NotifyHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

ALLOWED_TOOLS = {"Edit", "Write", "NotebookEdit"}

CHANGE_TYPE_BY_TOOL = {
    "Edit": "edit",
    "Write": "write",
    "NotebookEdit": "notebook_edit",
}


@dataclass
class HookInboxStats:
    bytes_read: int = 0
    events_processed: int = 0
    events_skipped: int = 0
    last_event_epoch: float | None = None


@dataclass
class HookInboxTailer:
    """Tails the Claude Code hook inbox JSONL.

    The notify_handler is invoked once per ingested event with a payload
    matching `engram.notify_file_changed`'s schema.
    """

    inbox_path: Path
    db_path: Path
    notify_handler: NotifyHandler
    poll_interval_s: float = 0.5
    stats: HookInboxStats = field(default_factory=HookInboxStats)
    _stop: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False)

    def start(self) -> asyncio.Task[None]:
        if self._task is not None:
            return self._task
        self._task = asyncio.create_task(self.run(), name="engram-hook-inbox")
        return self._task

    async def run(self) -> None:
        log.info("hook inbox tailer watching %s", self.inbox_path)
        while not self._stop.is_set():
            try:
                await self._tick_once()
            except Exception:
                log.exception("hook inbox tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval_s)
                return
            except TimeoutError:
                continue

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _tick_once(self) -> None:
        if not self.inbox_path.exists():
            return
        conn = open_db(self.db_path)
        try:
            cursor = int(meta_get(conn, META_CURSOR_KEY) or "0")
            size = self.inbox_path.stat().st_size
            if size < cursor:
                log.warning(
                    "hook inbox shrank from %d to %d; resetting cursor", cursor, size
                )
                cursor = 0
            if size == cursor:
                return
            new_cursor = await self._drain_from(conn, cursor)
            meta_set(conn, META_CURSOR_KEY, str(new_cursor))
        finally:
            conn.close()

    async def _drain_from(self, conn: sqlite3.Connection, cursor: int) -> int:
        with self.inbox_path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(cursor)
            while True:
                line = fh.readline()
                if not line:
                    cursor = fh.tell()
                    break
                if not line.endswith("\n"):
                    break
                cursor += len(line.encode("utf-8"))
                await self._dispatch(conn, line)
        return cursor

    async def _dispatch(self, conn: sqlite3.Connection, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            log.warning("hook inbox line is not JSON; skipping: %r", line[:80])
            self.stats.events_skipped += 1
            return

        payload = _to_notify_payload(event)
        if payload is None:
            self.stats.events_skipped += 1
            return

        self.stats.events_processed += 1
        self.stats.bytes_read += len(line)
        now = time.time()
        self.stats.last_event_epoch = now
        meta_set(conn, META_LAST_EVENT_AT, str(now))

        try:
            await self.notify_handler(payload)
        except Exception:
            log.exception("notify handler raised on event: %s", payload)


def _to_notify_payload(event: dict[str, Any]) -> dict[str, Any] | None:
    """Map a Claude Code PostToolUse JSON event to notify_file_changed args."""
    tool_name = event.get("tool_name")
    if tool_name not in ALLOWED_TOOLS:
        return None
    tool_input = event.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        return None
    response = event.get("tool_response") or {}
    if response and response.get("success") is False:
        return None
    return {
        "relative_path": file_path,
        "change_type": CHANGE_TYPE_BY_TOOL[tool_name],
        "source": "claude_code_hook",
        "tool": tool_name,
        "agent": "claude_code",
        "conversation_id": event.get("session_id"),
        "tool_use_id": event.get("tool_use_id"),
        "ts": event.get("ts") or time.time(),
    }

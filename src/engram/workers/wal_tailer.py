from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engram.link.store import meta_get, meta_set, open_db

log = logging.getLogger("engram.wal_tailer")

META_CURSOR_KEY = "mempalace_wal_cursor"
META_LAST_EVENT_AT = "mempalace_wal_last_event_at"


EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class WalTailerStats:
    bytes_read: int = 0
    events_processed: int = 0
    last_event_epoch: float | None = None


@dataclass
class WalTailer:
    """Tails MemPalace's append-only WAL and persists a byte-offset cursor.

    Runs as an asyncio task owned by the caller. Call `start()` inside a task
    group or `asyncio.create_task(tailer.run())` and `stop()` to shut down.
    """

    wal_path: Path
    db_path: Path
    poll_interval_s: float = 0.5
    handlers: list[EventHandler] = None  # type: ignore[assignment]
    stats: WalTailerStats = None  # type: ignore[assignment]
    _stop: asyncio.Event = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.handlers is None:
            self.handlers = []
        if self.stats is None:
            self.stats = WalTailerStats()
        self._stop = asyncio.Event()

    def on_event(self, handler: EventHandler) -> None:
        self.handlers.append(handler)

    async def run(self) -> None:
        log.info("wal tailer watching %s", self.wal_path)
        while not self._stop.is_set():
            try:
                await self._tick_once()
            except Exception:
                log.exception("wal tailer tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval_s)
                return
            except TimeoutError:
                continue

    def stop(self) -> None:
        self._stop.set()

    async def _tick_once(self) -> None:
        if not self.wal_path.exists():
            return
        conn = open_db(self.db_path)
        try:
            cursor = int(meta_get(conn, META_CURSOR_KEY) or "0")
            size = self.wal_path.stat().st_size
            if size < cursor:
                # WAL was rotated / truncated. Reset to 0.
                log.warning(
                    "wal shrank from %d to %d; resetting cursor", cursor, size
                )
                cursor = 0
            if size == cursor:
                return
            new_cursor = await self._drain_from(conn, cursor)
            meta_set(conn, META_CURSOR_KEY, str(new_cursor))
        finally:
            conn.close()

    async def _drain_from(self, conn: sqlite3.Connection, cursor: int) -> int:
        with self.wal_path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(cursor)
            while True:
                line = fh.readline()
                if not line:
                    cursor = fh.tell()
                    break
                if not line.endswith("\n"):
                    # Partial line; wait for the writer to flush the rest.
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
            log.warning("wal line is not JSON; skipping: %r", line[:80])
            return
        self.stats.events_processed += 1
        self.stats.bytes_read += len(line)
        now = time.time()
        self.stats.last_event_epoch = now
        meta_set(conn, META_LAST_EVENT_AT, str(now))
        for handler in self.handlers:
            try:
                await handler(event)
            except Exception:
                log.exception("wal handler raised on event: %s", event)


def wal_lag_seconds(db_path: Path) -> float | None:
    """Return seconds since the last observed WAL event, or None if never seen."""
    if not db_path.exists():
        return None
    conn = open_db(db_path)
    try:
        raw = meta_get(conn, META_LAST_EVENT_AT)
    finally:
        conn.close()
    if raw is None:
        return None
    try:
        last = float(raw)
    except ValueError:
        return None
    return round(max(0.0, time.time() - last), 2)

"""Background scheduler — periodic reconciler.

Runs `reconcile(scope="all")` every `interval_hours` (default 24). Owned by
the same task that runs the MCP server; cancelled cleanly on shutdown.
Updates `meta.last_reconcile_at` on every successful pass.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engram.link.store import meta_set, open_db
from engram.workers.reconciler import reconcile

log = logging.getLogger("engram.scheduler")

DrawerLookup = Callable[[str], Awaitable[dict[str, Any] | None]]

DEFAULT_INTERVAL_HOURS = 24.0


@dataclass
class ReconcilerScheduler:
    db_path: Path
    drawer_lookup: DrawerLookup | None = None
    interval_hours: float = DEFAULT_INTERVAL_HOURS
    _task: asyncio.Task | None = field(default=None, init=False)
    _stop: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    def start(self) -> asyncio.Task:
        if self._task is not None:
            return self._task
        self._task = asyncio.create_task(self._run(), name="engram-reconciler")
        return self._task

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _run(self) -> None:
        seconds = max(self.interval_hours * 3600.0, 60.0)
        log.info("reconciler scheduler started; interval=%.1f h", self.interval_hours)
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=seconds)
                return
            except TimeoutError:
                pass
            try:
                report = await reconcile(
                    self.db_path, scope="all", drawer_lookup=self.drawer_lookup
                )
                _record_pass(self.db_path)
                log.info("scheduled reconcile: changed=%s", report.changed)
            except Exception:
                log.exception("scheduled reconcile failed")


def _record_pass(db_path: Path) -> None:
    if not db_path.exists():
        return
    conn = open_db(db_path)
    try:
        meta_set(
            conn,
            "last_reconcile_at",
            dt.datetime.now(dt.UTC).isoformat(),
        )
    finally:
        conn.close()

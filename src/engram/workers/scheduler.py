"""Background scheduler — periodic reconciler + fast dirty sweep.

The full-scope reconcile runs every `interval_hours` (default 24). A
second, fast tick (`dirty_sweep_interval_seconds`, default 60s) calls
`reconcile(scope="chunks", paths=<dirty_files>)` to keep anchor freshness
within seconds of a Claude/Engram file change. Both tasks are cancelled
cleanly on shutdown.
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
from engram.workers.reconciler import collect_dirty_paths, reconcile

log = logging.getLogger("engram.scheduler")

DrawerLookup = Callable[[str], Awaitable[dict[str, Any] | None]]

DEFAULT_INTERVAL_HOURS = 24.0
DEFAULT_DIRTY_SWEEP_SECONDS = 60.0


@dataclass
class ReconcilerScheduler:
    db_path: Path
    drawer_lookup: DrawerLookup | None = None
    interval_hours: float = DEFAULT_INTERVAL_HOURS
    dirty_sweep_interval_seconds: float = DEFAULT_DIRTY_SWEEP_SECONDS
    _task: asyncio.Task | None = field(default=None, init=False)
    _fast_task: asyncio.Task | None = field(default=None, init=False)
    _stop: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    def start(self) -> asyncio.Task:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="engram-reconciler")
        if self._fast_task is None:
            self._fast_task = asyncio.create_task(
                self._run_fast(), name="engram-reconciler-fast"
            )
        return self._task

    async def stop(self) -> None:
        self._stop.set()
        for attr in ("_task", "_fast_task"):
            task = getattr(self, attr)
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            setattr(self, attr, None)

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

    async def _run_fast(self) -> None:
        seconds = max(self.dirty_sweep_interval_seconds, 5.0)
        log.info("dirty-sweep scheduler started; interval=%.1f s", seconds)
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=seconds)
                return
            except TimeoutError:
                pass
            try:
                paths = collect_dirty_paths(self.db_path)
                if not paths:
                    continue
                report = await reconcile(
                    self.db_path,
                    scope="chunks",
                    paths=paths,
                    drawer_lookup=self.drawer_lookup,
                )
                log.debug(
                    "dirty sweep: paths=%d, anchors_changed=%d",
                    len(paths),
                    report.changed.get("anchors", 0),
                )
            except Exception:
                log.exception("dirty sweep failed")


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

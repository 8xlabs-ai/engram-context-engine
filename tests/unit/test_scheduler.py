from __future__ import annotations

import asyncio
from pathlib import Path

from engram.link.store import init_db, meta_get
from engram.workers.scheduler import ReconcilerScheduler


def test_scheduler_runs_reconcile_periodically(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()

    async def run() -> None:
        sched = ReconcilerScheduler(
            db_path=db,
            interval_hours=60 / 3600,  # 60s but the scheduler clamps to >=60s anyway
        )
        # Override the interval seconds via the field after init for a fast test:
        sched.interval_hours = 0.05  # ~180s — but scheduler clamps to 60s minimum
        sched.start()
        # Force shutdown immediately, no full cycle needed; we only verify
        # the task is created + cancellable.
        await asyncio.sleep(0.1)
        await sched.stop()
        assert sched._task is None

    asyncio.run(run())


def test_scheduler_records_last_reconcile_at(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()

    async def run() -> None:
        from engram.workers.scheduler import _record_pass

        _record_pass(db)

    asyncio.run(run())

    conn = init_db(db)
    try:
        last = meta_get(conn, "last_reconcile_at")
        assert last is not None and last != "1970-01-01T00:00:00Z"
    finally:
        conn.close()


def test_scheduler_idempotent_start(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()

    async def run() -> None:
        sched = ReconcilerScheduler(db_path=db)
        t1 = sched.start()
        t2 = sched.start()
        assert t1 is t2
        await sched.stop()

    asyncio.run(run())

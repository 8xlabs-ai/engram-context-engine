from __future__ import annotations

import asyncio
import json
from pathlib import Path

from engram.link.store import init_db, meta_get
from engram.workers.wal_tailer import (
    META_CURSOR_KEY,
    WalTailer,
    wal_lag_seconds,
)


def _drive(tailer: WalTailer, iterations: int = 4) -> None:
    async def run() -> None:
        for _ in range(iterations):
            await tailer._tick_once()
            await asyncio.sleep(0.01)

    asyncio.run(run())


def _write_wal_lines(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")
        fh.flush()


def test_tailer_advances_cursor_and_invokes_handler(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    wal = tmp_path / "wal" / "write_log.jsonl"
    events = [{"op": "add_drawer", "drawer_id": f"D{i}"} for i in range(3)]
    _write_wal_lines(wal, events)

    captured: list[dict] = []

    async def handler(event: dict) -> None:
        captured.append(event)

    tailer = WalTailer(wal_path=wal, db_path=db, poll_interval_s=0.01)
    tailer.on_event(handler)
    _drive(tailer)

    assert [e["drawer_id"] for e in captured] == ["D0", "D1", "D2"]
    assert tailer.stats.events_processed == 3

    conn = init_db(db)
    try:
        cursor = int(meta_get(conn, META_CURSOR_KEY) or "0")
        assert cursor > 0
    finally:
        conn.close()


def test_tailer_resumes_from_persisted_cursor(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    wal = tmp_path / "wal" / "write_log.jsonl"

    _write_wal_lines(wal, [{"op": "add_drawer", "drawer_id": "D0"}])

    first: list[dict] = []

    async def h1(e: dict) -> None:
        first.append(e)

    t1 = WalTailer(wal_path=wal, db_path=db, poll_interval_s=0.01)
    t1.on_event(h1)
    _drive(t1)
    assert len(first) == 1

    _write_wal_lines(wal, [{"op": "add_drawer", "drawer_id": "D1"}])

    second: list[dict] = []

    async def h2(e: dict) -> None:
        second.append(e)

    t2 = WalTailer(wal_path=wal, db_path=db, poll_interval_s=0.01)
    t2.on_event(h2)
    _drive(t2)

    # t2 must see only D1; D0 was consumed by t1.
    assert [e["drawer_id"] for e in second] == ["D1"]


def test_tailer_skips_partial_line(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    wal = tmp_path / "wal" / "write_log.jsonl"
    wal.parent.mkdir(parents=True, exist_ok=True)
    with wal.open("w", encoding="utf-8") as fh:
        fh.write('{"op": "add_drawer", "drawer_id": "D0"}\n')
        fh.write('{"op": "add_drawer", "drawer_id": "D1"}')  # no trailing newline

    captured: list[dict] = []

    async def h(e: dict) -> None:
        captured.append(e)

    t = WalTailer(wal_path=wal, db_path=db, poll_interval_s=0.01)
    t.on_event(h)
    _drive(t)
    assert [e["drawer_id"] for e in captured] == ["D0"]

    with wal.open("a", encoding="utf-8") as fh:
        fh.write("\n")
    _drive(t)
    assert [e["drawer_id"] for e in captured] == ["D0", "D1"]


def test_tailer_handles_rotation_by_resetting(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    wal = tmp_path / "wal" / "write_log.jsonl"
    _write_wal_lines(wal, [{"op": "add_drawer", "drawer_id": f"D{i}"} for i in range(3)])

    captured: list[dict] = []

    async def h(e: dict) -> None:
        captured.append(e)

    t = WalTailer(wal_path=wal, db_path=db, poll_interval_s=0.01)
    t.on_event(h)
    _drive(t)
    assert len(captured) == 3

    # Rotation: new file with fewer bytes than the persisted cursor.
    wal.unlink()
    _write_wal_lines(wal, [{"op": "add_drawer", "drawer_id": "fresh"}])
    _drive(t)
    assert [e["drawer_id"] for e in captured] == ["D0", "D1", "D2", "fresh"]


def test_wal_lag_seconds_reports_after_event(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    wal = tmp_path / "wal" / "write_log.jsonl"
    _write_wal_lines(wal, [{"op": "add_drawer", "drawer_id": "D0"}])

    t = WalTailer(wal_path=wal, db_path=db, poll_interval_s=0.01)
    _drive(t)
    lag = wal_lag_seconds(db)
    assert lag is not None
    assert 0 <= lag < 5

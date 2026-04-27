from __future__ import annotations

import asyncio
import json
from pathlib import Path

from engram.link.store import init_db, meta_get
from engram.workers.wal_tailer import (
    META_CURSOR_KEY,
    META_INODE_KEY,
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


def test_tailer_persists_inode_meta(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    wal = tmp_path / "wal" / "write_log.jsonl"
    _write_wal_lines(wal, [{"op": "add_drawer", "drawer_id": "D0"}])

    t = WalTailer(wal_path=wal, db_path=db, poll_interval_s=0.01)
    _drive(t)

    expected_inode = wal.stat().st_ino
    conn = init_db(db)
    try:
        stored = int(meta_get(conn, META_INODE_KEY) or "0")
        assert stored == expected_inode
    finally:
        conn.close()


def test_tailer_silent_reset_on_inode_change(
    tmp_path: Path, caplog
) -> None:
    """Rotation (different inode) resets cursor without a 'truncated' warning."""
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
    first_inode = wal.stat().st_ino

    # Rotation: unlink + recreate gives a new inode on most filesystems.
    wal.unlink()
    _write_wal_lines(wal, [{"op": "add_drawer", "drawer_id": "fresh"}])
    second_inode = wal.stat().st_ino
    if second_inode == first_inode:  # pragma: no cover - filesystem-dependent
        return  # FS reused the inode; the same-inode path is exercised elsewhere.

    with caplog.at_level("WARNING", logger="engram.wal_tailer"):
        _drive(t)

    assert [e["drawer_id"] for e in captured] == ["D0", "D1", "D2", "fresh"]
    assert not any("truncated in place" in r.message for r in caplog.records)


def test_tailer_warns_on_in_place_truncation(tmp_path: Path, caplog) -> None:
    """Same inode but smaller size = real anomaly; logs a warning."""
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    wal = tmp_path / "wal" / "write_log.jsonl"
    _write_wal_lines(wal, [{"op": "add_drawer", "drawer_id": f"D{i}"} for i in range(3)])

    t = WalTailer(wal_path=wal, db_path=db, poll_interval_s=0.01)
    _drive(t)
    inode_before = wal.stat().st_ino

    # Truncate in place — opening with 'w' and writing small content keeps the
    # inode on POSIX filesystems.
    with wal.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"op": "add_drawer", "drawer_id": "post"}) + "\n")
    inode_after = wal.stat().st_ino
    if inode_after != inode_before:  # pragma: no cover - filesystem-dependent
        return  # FS allocated a new inode; the rotation path is tested elsewhere.

    captured: list[dict] = []

    async def h(e: dict) -> None:
        captured.append(e)

    t.handlers.append(h)

    with caplog.at_level("WARNING", logger="engram.wal_tailer"):
        _drive(t)

    assert any("truncated in place" in r.message for r in caplog.records)
    assert [e["drawer_id"] for e in captured] == ["post"]

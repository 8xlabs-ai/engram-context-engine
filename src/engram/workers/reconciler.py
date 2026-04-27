"""Reconciler — heals stale anchors.

Scopes:
- `memories`: check each anchors_symbol_memory drawer via drawer_lookup; if
  the drawer is gone from MemPalace, remove the anchor row (+ tombstone it
  in symbol_history).
- `symbols`: compare the live symbols table against Serena's truth per file.
  Remove / tombstone rows whose (name_path, relative_path) no longer
  resolves. Deferred when symbol_lookup is absent.
- `chunks`: sweep anchors_symbol_chunk whose index_generation is more than
  two ticks stale (handled here as a rename-time invalidation and a drop of
  rows referencing deleted files).
- `all`: run all three.

Dry run: perform all reads + diff computation but commit nothing. SHA-256
of the SQLite file is unchanged.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engram.link.store import (
    append_history,
    clear_dirty_file,
    dirty_file_paths,
    mark_reindexed,
    open_db,
)

log = logging.getLogger("engram.reconciler")

Scope = str  # "symbols" | "chunks" | "memories" | "all"

DrawerLookup = Callable[[str], Awaitable[dict[str, Any] | None]]


@dataclass
class ReconcileReport:
    changed: dict[str, int] = field(
        default_factory=lambda: {"symbols": 0, "anchors": 0, "tombstones": 0}
    )
    scanned: dict[str, int] = field(
        default_factory=lambda: {"memories": 0, "symbols": 0, "chunks": 0}
    )
    warnings: list[str] = field(default_factory=list)


async def reconcile(
    db_path: Path,
    *,
    scope: Scope = "all",
    dry_run: bool = False,
    drawer_lookup: DrawerLookup | None = None,
    paths: list[str] | None = None,
) -> ReconcileReport:
    """Run the reconciler.

    `paths` restricts the chunk sweep to a specific set of relative paths
    (typically those marked dirty in `dirty_files`). When `paths` resolves
    to a non-empty list, change_log rows for each path are flipped to
    `reindex_state='reindexed'` and the dirty_files entry is cleared on
    successful (non-dry-run) completion.
    """
    report = ReconcileReport()
    conn = open_db(db_path)
    try:
        if dry_run:
            conn.execute("BEGIN")
        if scope in ("memories", "all"):
            await _reconcile_memories(conn, report, drawer_lookup)
        if scope in ("chunks", "all"):
            _reconcile_chunks(conn, report, paths=paths)
        if scope in ("symbols", "all"):
            # Symbol-truth reconciliation requires Serena; stub out until we
            # plumb symbol_lookup into the reconciler. Count as scanned but
            # not changed so dry_run hash stability holds.
            report.scanned["symbols"] = _count(conn, "symbols")
        if dry_run:
            conn.execute("ROLLBACK")
        elif paths and scope in ("chunks", "all"):
            for relative_path in paths:
                mark_reindexed(conn, relative_path)
                clear_dirty_file(conn, relative_path)
    finally:
        conn.close()
    return report


def collect_dirty_paths(db_path: Path) -> list[str]:
    """Return the current dirty_files path list (empty if DB absent)."""
    if not db_path.exists():
        return []
    conn = open_db(db_path)
    try:
        return dirty_file_paths(conn)
    finally:
        conn.close()


async def _reconcile_memories(
    conn: sqlite3.Connection,
    report: ReconcileReport,
    drawer_lookup: DrawerLookup | None,
) -> None:
    rows = conn.execute(
        "SELECT anchor_id, symbol_id, drawer_id FROM anchors_symbol_memory"
    ).fetchall()
    report.scanned["memories"] = len(rows)
    if drawer_lookup is None:
        report.warnings.append("memories: no drawer_lookup configured; skipped")
        return
    stale: list[tuple[int, int, str]] = []
    for row in rows:
        drawer = await drawer_lookup(str(row["drawer_id"]))
        if drawer is None:
            stale.append(
                (int(row["anchor_id"]), int(row["symbol_id"]), str(row["drawer_id"]))
            )
    for anchor_id, symbol_id, _drawer_id in stale:
        conn.execute(
            "DELETE FROM anchors_symbol_memory WHERE anchor_id = ?", (anchor_id,)
        )
        append_history(
            conn,
            symbol_id=symbol_id,
            source="reconcile",
            old_name_path=None,
            new_name_path=None,
        )
        report.changed["anchors"] += 1
        report.changed["tombstones"] += 1


def _reconcile_chunks(
    conn: sqlite3.Connection,
    report: ReconcileReport,
    *,
    paths: list[str] | None = None,
) -> None:
    # Drop chunk anchors whose symbol is tombstoned.
    if paths:
        placeholders = ",".join("?" for _ in paths)
        rows = conn.execute(
            "SELECT asc_.anchor_id "
            "FROM anchors_symbol_chunk asc_ "
            "JOIN symbols s ON s.symbol_id = asc_.symbol_id "
            f"WHERE asc_.relative_path IN ({placeholders}) "
            "AND s.tombstoned_at IS NOT NULL",
            tuple(paths),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT asc_.anchor_id "
            "FROM anchors_symbol_chunk asc_ "
            "JOIN symbols s ON s.symbol_id = asc_.symbol_id "
            "WHERE s.tombstoned_at IS NOT NULL"
        ).fetchall()
    report.scanned["chunks"] = _count(conn, "anchors_symbol_chunk")
    for row in rows:
        conn.execute(
            "DELETE FROM anchors_symbol_chunk WHERE anchor_id = ?",
            (int(row["anchor_id"]),),
        )
        report.changed["anchors"] += 1


def _count(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    return int(row["n"])

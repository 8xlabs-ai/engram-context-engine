## ADDED Requirements

### Requirement: Anchor store schema

The system SHALL persist anchors and symbol identity in a SQLite database at `.engram/anchors.sqlite`, opened in WAL journal mode with a single writer. The schema SHALL contain exactly seven tables — `symbols`, `symbol_history`, `drawers`, `chunks`, `anchors_symbol_memory`, `anchors_symbol_chunk`, `anchors_memory_chunk` — and three unique partial indices that prevent duplicate anchors for the same `(symbol_id, drawer_id)`, `(symbol_id, chunk_id)`, and `(drawer_id, chunk_id)` pairs.

#### Scenario: Fresh install produces the documented schema

- **WHEN** `engram init` completes on an empty workspace
- **THEN** `sqlite3 .engram/anchors.sqlite '.schema'` output SHALL include the seven table definitions and the three unique partial indices, byte-for-byte matching the fixture in `tests/fixtures/schema.sql`.

#### Scenario: Duplicate anchor insertion is a no-op

- **WHEN** the caller invokes `engram.anchor_memory_to_symbol` twice with identical `(drawer_id, name_path, relative_path)` arguments
- **THEN** the second call SHALL return the `anchor_id` from the first insert with no duplicate row created, and the response SHALL succeed (not raise `duplicate-anchor` as an error).

### Requirement: Symbol rename preserves anchor correctness

When a symbol is renamed via `code.rename_symbol`, the system SHALL update `symbols.name_path`, append a new `symbol_history` row with `change_kind='rename'`, and keep all anchors pointing to the same `symbol_id` — all within the same Engram response and atomically with the upstream Serena call.

#### Scenario: Successful rename updates symbol identity and history

- **WHEN** the caller invokes `code.rename_symbol(name_path="Foo/process", new_name="run")` on a workspace with one anchored drawer
- **THEN** Serena SHALL return success, `symbols.name_path` SHALL equal `"Foo/run"`, `symbol_history` SHALL contain a new row with `change_kind='rename'` and `previous_name_path='Foo/process'`, and the `anchors_symbol_memory` row SHALL still reference the same `symbol_id`.

#### Scenario: Upstream rename failure rolls back

- **WHEN** Serena `rename_symbol` returns an error (e.g., LSP crash)
- **THEN** the SQLite transaction SHALL roll back, `symbols.name_path` SHALL be unchanged, no new `symbol_history` row SHALL be appended, and the Engram response SHALL carry `error.code="consistency-state-hint"` with details naming the affected `symbol_id`.

### Requirement: KG tracks entity renames without mutating drawers

On a successful symbol rename, the system SHALL record the rename in the MemPalace knowledge graph by inserting a triple `(old_name, renamed_to, new_name)` with `valid_from=now` and invalidating prior identity triples for `old_name` with `valid_to=now`. The system SHALL NOT rewrite, edit, or replace any drawer content — MemPalace drawers are verbatim and append-only.

#### Scenario: Rename records KG provenance, leaves drawers untouched

- **WHEN** `code.rename_symbol` completes successfully on a symbol with one anchored drawer whose content quotes the old name
- **THEN** `mem.kg_query(subject=old_name)` SHALL return at least one triple with predicate `renamed_to` and object equal to the new name and `valid_from` within the last second, AND `mem.get(drawer_id=D)` SHALL return the drawer with its original content unchanged.

### Requirement: MemPalace WAL tailer observes external writes

The system SHALL tail MemPalace's append-only WAL at `~/.mempalace/wal/write_log.jsonl`, persist the byte-offset cursor in `.engram/state/wal_cursor.json`, and surface lag through `engram.health.upstreams.mempalace.wal_lag_seconds`. Observed writes SHALL become available for anchor reconciliation within 2 seconds of appearing in the WAL.

#### Scenario: Drawer write is observed within the lag budget

- **WHEN** a caller invokes `mem.add` and MemPalace confirms the write
- **THEN** within 2 seconds `engram.health.upstreams.mempalace.wal_lag_seconds` SHALL report a value ≤ 2.0 AND the WAL cursor on disk SHALL advance past the newly observed entry.

#### Scenario: Cursor survives restart

- **WHEN** Engram is stopped after tailing N WAL entries, then restarted
- **THEN** the tailer SHALL resume reading from the persisted offset and SHALL NOT re-process any previously observed entry.

### Requirement: Reconciler heals stale anchors

The system SHALL provide a reconciler job invocable via `engram.reconcile` or on a 24-hour schedule that detects anchors pointing to deleted drawers, renamed symbols not observed through the Engram rename flow, and moved files. It SHALL remove dangling rows, update `symbols` where identity changed, and report counts via the response `{changed: {symbols, anchors, tombstones}}`.

#### Scenario: Dry-run reports without mutating

- **WHEN** `engram.reconcile(scope="all", dry_run=true)` is invoked
- **THEN** the response SHALL list counts of rows that would be changed AND no row in any Link Layer table SHALL be modified (byte-identical DB checksum before and after).

#### Scenario: Live run removes dangling memory anchors

- **GIVEN** an `anchors_symbol_memory` row exists for `drawer_id=D`
- **WHEN** drawer `D` is deleted directly from MemPalace's Chroma store (bypassing Engram) and `engram.reconcile(scope="memories")` is invoked
- **THEN** the dangling `anchors_symbol_memory` row SHALL be removed, the response SHALL report `changed.anchors >= 1`, and a tombstone SHALL be recorded in `symbol_history` with `change_kind='memory_tombstone'`.

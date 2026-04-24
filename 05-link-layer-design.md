# 05 — Link Layer Design

> Status: **draft**. This document specifies the anchor store, the population events that maintain it, rename / move propagation per upstream, consistency semantics, and the hook-bus contract that Engram's internal modules subscribe to. Assumes **Shape-A (MCP-client orchestrator)** per doc 04.

The Link Layer is the first of Engram's two new pieces of substance. Its job is to answer, correctly and cheaply, three questions that no upstream answers:

1. **Given a symbol, what memories talk about it?** (`symbol↔memory`)
2. **Given a symbol, what vector chunks embed it?** (`symbol↔chunk`)
3. **Given a memory, what chunk(s) is it anchored to?** (`memory↔chunk`)

All three anchors must survive code motion (renames, file moves), be correctible from upstream truth (Serena symbol location, claude-context chunk location, MemPalace drawer id), and be queryable in microseconds from the Retrieval Router (doc 06).

## 1. Storage choice — SQLite

- **Local-first.** Anchors are per-workspace and do not need to survive a node crash or be shared across machines in v1.
- **Single-writer.** Engram's router and anchor-maintenance workers all run inside one Python process; SQLite's WAL mode is sufficient.
- **Schema evolution is easy.** `PRAGMA user_version` + additive migrations.
- **Rejected alternatives:** Postgres (operational cost; no multi-host need in v1), a bespoke JSONL (loses indices — the router's fusion path needs indexed joins), Redis (volatile; loses the "survive restart" property).

**Database path:** `.engram/anchors.sqlite` at the workspace root, created by `engram init` (doc 09). Concurrency model: one writer (anchor-maintenance worker), many readers (router). `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`.

## 2. Schema

All DDL below is canonical — engineers implementing this should copy it verbatim.

```sql
PRAGMA user_version = 1;

-- Normalized symbol identity. We do not store symbol name_path as the join key
-- directly because renames make it non-stable. Instead we assign a stable
-- internal symbol_id that follows a symbol across renames.
CREATE TABLE symbols (
    symbol_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name_path       TEXT NOT NULL,                 -- current LSP name_path, e.g. "Foo/process"
    relative_path   TEXT NOT NULL,                 -- current project-relative file path
    kind            INTEGER NOT NULL,              -- Serena SymbolKind int
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at    TEXT NOT NULL DEFAULT (datetime('now')),
    tombstoned_at   TEXT                           -- NULL while live; set on delete
);
CREATE INDEX idx_symbols_namepath ON symbols(name_path);
CREATE INDEX idx_symbols_path ON symbols(relative_path);
CREATE UNIQUE INDEX idx_symbols_current_identity
    ON symbols(relative_path, name_path)
    WHERE tombstoned_at IS NULL;

-- Symbol ↔ memory (drawer) anchors. One memory may anchor to many symbols,
-- one symbol may anchor to many memories.
CREATE TABLE anchors_symbol_memory (
    anchor_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id       INTEGER NOT NULL REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    drawer_id       TEXT NOT NULL,                 -- MemPalace drawer_id
    wing            TEXT NOT NULL,                 -- MemPalace wing (for fast filter)
    room            TEXT NOT NULL,
    created_by      TEXT NOT NULL,                 -- "explicit" | "j1-discovery" | "reconcile" | <engram tool>
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    confidence      REAL NOT NULL DEFAULT 1.0      -- 0.0–1.0; reconciliation may lower
);
CREATE INDEX idx_asm_symbol ON anchors_symbol_memory(symbol_id);
CREATE INDEX idx_asm_drawer ON anchors_symbol_memory(drawer_id);
CREATE UNIQUE INDEX idx_asm_identity ON anchors_symbol_memory(symbol_id, drawer_id);

-- Symbol ↔ chunk anchors. Chunks are identified by (relative_path, start_line,
-- end_line) because claude-context does not expose stable chunk IDs in its
-- result shape (03 §7).
CREATE TABLE anchors_symbol_chunk (
    anchor_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id       INTEGER NOT NULL REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    relative_path   TEXT NOT NULL,
    start_line      INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    language        TEXT NOT NULL,
    index_generation INTEGER NOT NULL,             -- claude-context re-index tick counter
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_asc_symbol ON anchors_symbol_chunk(symbol_id);
CREATE INDEX idx_asc_path ON anchors_symbol_chunk(relative_path, start_line, end_line);
CREATE UNIQUE INDEX idx_asc_identity
    ON anchors_symbol_chunk(symbol_id, relative_path, start_line, end_line);

-- Memory ↔ chunk anchors. Less common than the other two kinds (a memory
-- directly tied to a vector chunk rather than to a symbol). Used when Engram
-- surfaces a memory that was captured *about a chunk* (e.g., a code review
-- comment on a specific line range).
CREATE TABLE anchors_memory_chunk (
    anchor_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    drawer_id       TEXT NOT NULL,
    relative_path   TEXT NOT NULL,
    start_line      INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    language        TEXT NOT NULL,
    index_generation INTEGER NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_amc_drawer ON anchors_memory_chunk(drawer_id);
CREATE INDEX idx_amc_path ON anchors_memory_chunk(relative_path, start_line, end_line);
CREATE UNIQUE INDEX idx_amc_identity
    ON anchors_memory_chunk(drawer_id, relative_path, start_line, end_line);

-- Rename / move history. Append-only. Drives Engram's "what used to be here?"
-- queries and the consistency reconciler.
CREATE TABLE symbol_history (
    history_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id       INTEGER NOT NULL REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    at_time         TEXT NOT NULL DEFAULT (datetime('now')),
    old_name_path   TEXT,                          -- NULL at creation
    new_name_path   TEXT,                          -- NULL at deletion
    old_path        TEXT,
    new_path        TEXT,
    source          TEXT NOT NULL                  -- "engram-rename" | "reconcile" | "import"
);
CREATE INDEX idx_hist_symbol ON symbol_history(symbol_id);

-- Meta table. Cursor for the MemPalace WAL tail, last reconciliation tick for
-- claude-context, and schema version.
CREATE TABLE meta (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Seed keys inserted at init:
-- ('mempalace_wal_cursor', '0')
-- ('last_reconcile_at', '1970-01-01T00:00:00Z')
-- ('claude_context_index_generation', '0')
```

**Notes.**

- `symbols.tombstoned_at` rather than a hard delete preserves anchor history across `safe_delete_symbol`. A tombstoned row still participates in `symbol_history` joins.
- The unique partial index `idx_symbols_current_identity` (on `WHERE tombstoned_at IS NULL`) forbids two live symbols having the same `(path, name_path)` but allows old tombstones to coexist.
- `confidence` on `anchors_symbol_memory` gives the reconciler a way to degrade anchors it can no longer verify, instead of deleting them.
- All `relative_path` values are normalized to forward-slash, project-relative (`engram.util.normalize_path`). No absolute paths ever stored.
- `index_generation` in the two chunk-carrying tables pins a chunk anchor to a claude-context re-index tick so we can detect stale chunks after an index refresh. Incremented by the reconciler every time the Merkle snapshot at `~/.context/merkle/<md5>.json` advances.

## 3. Population events per anchor kind

The Link Layer's correctness hinges on where each anchor row comes from and who maintains it. The three sources, in decreasing order of reliability:

1. **Engram-initiated writes** — deterministic and authoritative.
2. **WAL-tail observations** (MemPalace) — reliable to the WAL's durability.
3. **Periodic reconciliation** — best-effort, bounded by the sync tick.

### 3.1 `symbols` table — population

Sources, in order of authority:

- **Symbol-first discovery (reliable).** When Engram calls Serena `find_symbol` (01 §2), the returned `name_path` + location is upserted into `symbols`. `last_seen_at = now`. If a row with the same `(relative_path, name_path)` exists, update only `last_seen_at`.
- **Rename propagation (authoritative).** When Engram dispatches a Serena `rename_symbol` (01 §2), Engram updates the `symbols` row for the target symbol *before* forwarding the call, so a concurrent reader doesn't see the old identity. A row in `symbol_history` is appended inside the same transaction.
- **Tombstoning.** When Engram dispatches `safe_delete_symbol` (01 §2) and Serena reports success, Engram sets `tombstoned_at = now` on the `symbols` row.
- **Reconciliation fallback.** Every reconciliation tick (§5) walks the project via Serena `get_symbols_overview` and upserts missing rows / tombstones stale ones that no longer resolve.

### 3.2 `anchors_symbol_memory` — population

- **Explicit anchor write.** A new Engram MCP tool `engram.anchor_memory_to_symbol(drawer_id, name_path, relative_path)` is the primary public API (doc 07). Resolves the symbol (creates if necessary), inserts the anchor row with `created_by="explicit"`, returns the `anchor_id`.
- **Implicit from J1/J2/J6 (see doc 04).** When a join flow surfaces "memory M is relevant to symbol S," the router may insert a weak anchor (`confidence=0.5, created_by="j1-discovery"`). Anchors below `0.5` are invisible to the Retrieval Router unless `include_weak=true`.
- **WAL-tail observation.** When the MemPalace WAL emits an `add_drawer` event whose metadata carries an `anchored_symbol` hint (Engram's own tool can set this in MemPalace metadata when writing), Engram inserts a `created_by="wal"` anchor.
- **Reconciliation.** Every 24 h, Engram may re-run `mempalace_search` for the name_path of each live symbol and insert anchors for drawers above a similarity threshold, marked `created_by="reconcile", confidence=0.5`.

### 3.3 `anchors_symbol_chunk` — population

This is the hardest anchor kind because claude-context does not emit chunk-indexing events (03 §6) and chunks lack stable IDs.

- **On-demand resolution (lazy).** When the router performs J2 (doc 04 — discovery → precision), it calls claude-context `search_code` (03 §2) and receives chunk rows with `(relativePath, startLine, endLine)`. For each, Engram calls Serena `get_symbols_overview(relative_path=relativePath)` and picks the innermost symbol whose range contains the chunk's line span. The resulting anchor is inserted with the current `index_generation`.
- **Bulk seeding (cold start).** After `engram init` triggers `index_codebase` on claude-context for the first time, Engram walks every indexed file, asks Serena for symbols overview, and anchors each (chunk, enclosing-symbol) pair. This is the one heavy job; it's amortized against first-time indexing.
- **Re-index tick.** On each claude-context 5-minute tick (or the Engram-triggered fast path in M4), Engram reads the `added / removed / modified` file lists (via calling claude-context's core JS `reindexByChange()` through a thin Node shim introduced in M4) and refreshes the anchors on those files only.

### 3.4 `anchors_memory_chunk` — population

- **Explicit anchor write** via `engram.anchor_memory_to_chunk(drawer_id, relative_path, start_line, end_line)`. Used when a memory is intentionally about a range (code review, TODO explanation).
- **Derived from `symbol_memory` + `symbol_chunk`.** The router can compute `memory↔chunk` as a join of the two primary tables. Materializing the explicit `anchors_memory_chunk` rows is reserved for the explicit case; joined results are ephemeral.

## 4. Rename / move propagation per upstream

This is the section most engineers will actually read. The strategy varies per upstream because the observability surfaces vary (01 §8, 02 §10, 03 §6).

### 4.1 Serena — source is Engram's own dispatch

**Claim:** Serena does not observe external edits (01 §8). Therefore Engram only learns about renames/moves when Engram itself dispatches the tool call.

**Engram-initiated rename flow.**

1. User agent calls Engram MCP `code.rename_symbol(name_path, relative_path, new_name)` (doc 07).
2. Engram resolves `symbol_id` from `symbols` (name_path + path). If missing, call Serena `find_symbol` first to populate.
3. Engram begins a DB transaction: update `symbols.name_path = new_name`, append `symbol_history` row with `source="engram-rename"`, keep same `symbol_id`.
4. Engram forwards the call to Serena's `rename_symbol` tool (01 §2, `symbol_tools.py:410-435`). On success, commit.
5. On failure from Serena, rollback the DB transaction.

**Engram-initiated move flow.**

When a move changes the containing file (e.g., Serena's `jetbrains_move` tool, 01 §2; or a Python refactor that manually moves a symbol), the `relative_path` column is updated in the same transaction. The line range is re-resolved via `find_symbol` after the move.

**External rename invisibility.**

If a developer renames a symbol in their own editor without going through Engram, Serena will only notice on the next query (and even then only if its LSP cache is invalidated; see `restart_language_server` at `symbol_tools.py:21`). Mitigation:

- The reconciler (§5) runs `get_symbols_overview` on every file in the project daily. Rows whose `(relative_path, name_path)` no longer resolves get `tombstoned_at` set. New symbols get inserted.
- The stale-window bound is therefore **24 h at worst, 5 min at best** if the developer's file save triggers Engram's own watcher (M4).

### 4.2 MemPalace — source is WAL tail

**Claim:** MemPalace writes are fully observable via `~/.mempalace/wal/write_log.jsonl` (02 §10).

**WAL-tail flow.**

1. A dedicated `engram.workers.wal_tailer` reads from the MemPalace WAL starting at the cursor stored in `meta.mempalace_wal_cursor`.
2. For each entry, the tailer emits an event on the in-process hook bus (§6) and updates the cursor.
3. Relevant event types: `add_drawer`, `delete_drawer`, `update_drawer` (02 §10).
4. Anchors are updated:
   - `add_drawer` with `wing`, `room` → index the drawer in the Link Layer (no change to anchor tables unless the Engram-side tool call that caused the write also carried a symbol anchor hint).
   - `update_drawer` that changes `(wing, room)` → update cached metadata columns on `anchors_symbol_memory` rows for that `drawer_id`.
   - `delete_drawer` → SQL `DELETE` from `anchors_symbol_memory` and `anchors_memory_chunk` where `drawer_id = ?`.

**Reliability.** The MemPalace WAL is atomic-append with `O_WRONLY|O_APPEND|O_CREAT` (02 §10). The tailer persists its cursor after processing each line, so a crash at worst re-processes the last line (idempotent). WAL write failures in MemPalace are logged to stderr but still allow the operation (02 §10) — this means Engram may rarely miss an event. Mitigation: the reconciler (§5) periodically diffs Engram's anchor-store drawer list against a fresh `mempalace_list_drawers` (02 §2 entry #23) and repairs discrepancies.

### 4.3 claude-context — source is re-index tick

**Claim:** claude-context runs a 5-minute Merkle-DAG re-index (03 §6). It does not emit events; it rebuilds the snapshot file at `~/.context/merkle/<md5>.json`.

**Tick flow.**

1. Engram's `engram.workers.cc_reconciler` polls `~/.context/merkle/<md5>.json`'s mtime every 60 s (cheap).
2. When mtime advances, the reconciler:
   - Reads the new snapshot diff (calls claude-context's JS API via a small Node shim, introduced in M4; before M4 the reconciler just bumps `claude_context_index_generation` and drops stale `anchors_symbol_chunk` rows whose `index_generation` is older than N-2, falling back to on-demand re-anchoring).
   - For each `modified` or `removed` file, `DELETE FROM anchors_symbol_chunk WHERE relative_path = ?` and `DELETE FROM anchors_memory_chunk WHERE relative_path = ?`.
   - For each `added` or `modified` file, call claude-context `search_code(path=<workspace>, query=<filename>, extensionFilter=[<ext>])` to seed the chunk list, then anchor each chunk to its enclosing symbol as in §3.3 on-demand resolution.

**Stale window.** Chunk anchors can be out-of-date by up to one re-index tick (5 min default; 60 s in M4 with the watcher shim). The router (doc 06) tolerates this by always reconciling chunk line ranges against Serena `get_symbols_overview` before acting on a chunk anchor older than the stale-window budget.

## 5. Consistency semantics

### 5.1 Which upstream wins when they disagree?

**Serena wins on symbol identity and file location** — it has LSP-backed truth. If `symbols.relative_path = "foo.py"` but Serena `find_symbol` returns the same name_path at `bar.py`, Serena wins: Engram records a move in `symbol_history` and updates `symbols.relative_path`.

**MemPalace wins on drawer identity and content** — it is the authoritative source of memories. If a `drawer_id` in `anchors_symbol_memory` no longer appears in `mempalace_get_drawer` (02 §2 entry #22), Engram deletes the anchor.

**claude-context wins on chunk line ranges** — but only for a given `index_generation`. Engram never trusts a chunk anchor older than N-2 tick generations; it re-resolves against Serena if the generation window has passed.

### 5.2 What if Serena says `foo.py:42` and claude-context says `foo.py:40`?

This is the most common disagreement: Serena's LSP location is live-accurate, claude-context's line numbers are from the last re-index.

- The router asks Serena first when precision is required.
- When the router consumes a chunk anchor that is older than `index_generation - 2`, it re-queries Serena to confirm the line range and, if different, updates the anchor and bumps `index_generation` on the row.
- If Serena and claude-context disagree on current chunk line ranges (Serena says start_line=42, chunk anchor says start_line=40), Serena wins; Engram re-anchors the chunk to the closest symbol whose range contains Serena's new location.

### 5.3 Stale-window budget

| Anchor kind | Worst-case staleness in Shape-A (MCP) | With M4 shims |
|---|---|---|
| `symbols` (identity) | 24 h (daily reconcile) | 5 min (watcher tick) |
| `anchors_symbol_memory` | Real-time for Engram-initiated; WAL tail latency (~1 s) for external writes | same |
| `anchors_symbol_chunk` | 5 min (claude-context tick) | 60 s (Node-shim watcher) |
| `anchors_memory_chunk` | same as symbol_chunk | same |

These are the budgets the Retrieval Router (doc 06) must design around.

### 5.4 Idempotency

- All anchor inserts use `INSERT OR IGNORE` against the unique `idx_*_identity` indices. Duplicate inserts are no-ops, not errors.
- WAL-tail processing is idempotent by design: the cursor advances only after a successful insert-or-ignore, and a re-read of the same line is harmless.
- Reconciler inserts carry `created_by='reconcile'`; on collision with a stronger `created_by='explicit'` row, the reconciler does not overwrite.

## 6. Hook bus contract

An in-process pub/sub inside Engram, consumed by the Router (doc 06) and by feature modules (doc 08). Explicitly *not* a cross-process event system — nothing leaves Engram's process.

### 6.1 Event types

| Event | Payload | Producer | Example consumer |
|---|---|---|---|
| `symbol.created` | `{symbol_id, name_path, relative_path, kind}` | Serena-call wrapper; reconciler | Router pre-warm cache |
| `symbol.renamed` | `{symbol_id, old_name_path, new_name_path, at_time}` | Engram-rename dispatch | KG updater (J3 flow, doc 04) |
| `symbol.moved` | `{symbol_id, old_path, new_path, at_time}` | Engram-move dispatch; reconciler | chunk-anchor invalidator |
| `symbol.tombstoned` | `{symbol_id, at_time}` | Serena-call wrapper | anchor cleaner |
| `memory.written` | `{drawer_id, wing, room, operation}` | WAL-tail worker | J4 contradiction checker |
| `memory.deleted` | `{drawer_id}` | WAL-tail worker | anchor cleaner |
| `chunk.generation_advanced` | `{new_generation, changed_paths}` | cc-reconciler | anchor invalidator |

### 6.2 Ordering guarantees

- Events for a single `symbol_id` arrive in causal order (creation → rename(s) → tombstone). This is guaranteed by the Engram-rename dispatch being synchronous with DB commit.
- Events across symbols are **not** ordered.
- `memory.*` events arrive in MemPalace's WAL order, because the tailer processes the WAL sequentially.
- Cross-producer ordering is not guaranteed: a `symbol.renamed` and a `memory.written` referencing the new name may arrive in either order.

### 6.3 Delivery semantics

- **At-least-once.** Each consumer is responsible for idempotent handling. The anchor tables' unique indices make insert-paths idempotent.
- **Best-effort on restart.** On process restart, the WAL-tail worker resumes from its persisted cursor. The Engram-rename wrapper replays any events whose DB state hasn't been observed yet (compare `symbol_history` last entry to last consumer checkpoint in `meta`).

### 6.4 Implementation sketch

Plain Python `asyncio.Queue` per subscriber. Central dispatcher maintains a list of `(event_pattern, queue)` tuples; each producer calls `dispatcher.publish(event_type, payload)`. Keep it boring — this is not a distributed system.

## 7. Failure modes and recovery

| Failure | Behavior | Mitigation |
|---|---|---|
| SQLite DB corrupt | Engram fails to start | `engram init --rebuild-anchors` repopulates from live upstream state |
| MemPalace WAL path missing | WAL-tail worker logs + retries every 10 s | Worker does not block Engram startup |
| Serena down | Engram returns 503 on tools that require symbol resolution | Router's J2 flow short-circuits to pure chunk results if Serena unavailable |
| claude-context down | `code.search_chunks` returns empty + error envelope; J1/J4/J6 paths still function | Router uses cached chunk anchors where available |
| Rename transaction partial (Serena commit fails mid-flight) | Engram rolls back DB tx; user-visible error includes a "consistency state" hint | No manual repair needed |
| WAL tail falls behind (huge backlog) | Tailer processes sequentially; router continues serving reads against possibly stale anchors; `memory.written` events delayed | Expose `/engram/health` metric `wal_lag_seconds` |

## 8. Implications for downstream docs

- **Doc 06** (Router) treats the anchor tables as pre-indexed joins — query latency budget per anchor lookup is a single indexed SQLite read.
- **Doc 07** (MCP surface) adds four new `engram.*` tools: `engram.anchor_memory_to_symbol`, `engram.anchor_memory_to_chunk`, `engram.why` (the J1 flow), `engram.where_does_decision_apply` (J5).
- **Doc 08** (feature mapping) keeps features that operate inside the stale-window budget and cuts or defers features that need sub-second global rename visibility.
- **Doc 10** (roadmap) places: M1 = anchor store + Engram-rename wrapper + WAL tailer. M2 = router + on-demand chunk resolution. M3 = reconciler + daily full scan. M4 = Node-shim watcher for sub-minute claude-context sync.

## Assumptions

- SQLite's busy-timeout of 5 s is sufficient under expected load (one router process, one tailer, one reconciler). Measured contention in M1 may force raising it.
- MemPalace's WAL rotation policy was not observed — the brief `02 §10` does not specify whether old WAL entries are truncated. If they are rotated / compacted, the cursor bookkeeping may need to widen to `(file_name, offset)` instead of `(offset)`. Logged in doc 11.
- Daily full reconciliation is assumed cheap on small-to-medium codebases (≤100k symbols). Large monorepos may need an incremental reconciler; scope-cut for v1.

# 02 — Upstream Inventory: MemPalace

> Status: **draft**. Cited investigation of the MemPalace repo at `/Users/zaghloul/Projects/accelerate-workspace/mempalace/`. Version `3.3.3`, MIT. Every structural claim carries a `mempalace/path:line` citation.

MemPalace is a local-first, zero-API-key memory system for AI agents. It stores **verbatim** conversation/project content in a palace structure (wings → rooms → drawers), indexes via hybrid BM25 + vector retrieval (ChromaDB), and maintains a separate temporal SQLite knowledge graph.

## 1. Entrypoints

`mempalace/pyproject.toml:40-42` declares two scripts:

- `mempalace = "mempalace.cli:main"` — CLI dispatcher.
- `mempalace-mcp = "mempalace.mcp_server:main"` — MCP server over stdio.

`mempalace/__main__.py:3-5` additionally allows `python -m mempalace`.

Config loading is in `MempalaceConfig()` (`mempalace/config.py`): environment first, then `~/.mempalace/config.json` if present, else defaults. Default palace path: `~/.mempalace/palace`. Default KG path: `~/.mempalace/knowledge_graph.sqlite3` (`mempalace/knowledge_graph.py:47`), overridden to `{palace_path}/knowledge_graph.sqlite3` when `--palace` is supplied (`mempalace/mcp_server.py:101`).

## 2. MCP surface — complete and exhaustive (29 tools)

Registered in the `TOOLS` dict at `mempalace/mcp_server.py:1161`. Handler functions are dispatched from the same file.

| # | Tool | Handler file:line | Inputs | Output | Behavior |
|---|---|---|---|---|---|
| 1 | `mempalace_status` | `mcp_server.py:1167` | — | `{total_drawers, wings, rooms, palace_path, protocol, aaak_dialect, [error]}` | Palace overview + protocol spec. |
| 2 | `mempalace_list_wings` | `:1173` | — | `{wings: {name: count}, [error]}` | All wings with drawer counts. |
| 3 | `mempalace_list_rooms` | `:1179` | `wing?: str` | `{rooms: {name: count}, [error]}` | Rooms in a wing or all rooms. |
| 4 | `mempalace_get_taxonomy` | `:1188` | — | Nested `{wings: {wing: {rooms: {room: count}}}}` | Full tree. |
| 5 | `mempalace_get_aaak_spec` | `:1195` | — | `{aaak_spec: str}` | AAAK compression reference document. |
| 6 | `mempalace_kg_query` | `:1202` | `entity`, `as_of?`, `direction?` | `{entity, as_of, facts: [...], count}` | Query KG relationships with temporal filter. |
| 7 | `mempalace_kg_add` | `:1222` | `subject`, `predicate`, `object`, `valid_from?`, `source_closet?` | `{success, triple_id, fact}` | Add KG fact. |
| 8 | `mempalace_kg_invalidate` | `:1250` | `subject`, `predicate`, `object`, `ended?` | `{success, fact, ended}` | Set `valid_to` on matching triples. |
| 9 | `mempalace_kg_timeline` | `:1267` | `entity?` | `{entity, facts: [...]}` | Chronological facts. |
| 10 | `mempalace_kg_stats` | `:1282` | — | `{total_entities, total_triples, current_facts, expired_facts, relationship_types}` | KG stats. |
| 11 | `mempalace_traverse` | `:1290` | `start_room`, `max_hops?` | `{room, connections: [...]}` | Walk palace graph across wings. |
| 12 | `mempalace_find_tunnels` | `:1307` | `wing_a?`, `wing_b?` | `{tunnels: [...]}` | Find rooms bridging two wings. |
| 13 | `mempalace_graph_stats` | `:1317` | — | `{total_rooms, total_tunnels, edges_between_wings}` | Graph connectivity. |
| 14 | `mempalace_create_tunnel` | `:1323` | `source_wing`, `source_room`, `target_wing`, `target_room`, `label?`, `source_drawer_id?`, `target_drawer_id?` | `{success, tunnel_id}` | Create cross-wing tunnel. |
| 15 | `mempalace_list_tunnels` | `:1347` | `wing?` | `{tunnels: [...]}` | List tunnels. |
| 16 | `mempalace_delete_tunnel` | `:1360` | `tunnel_id` | `{success}` | Delete tunnel. |
| 17 | `mempalace_follow_tunnels` | `:1372` | `wing`, `room` | `{room, connections: [...]}` | Follow tunnels, previews included. |
| 18 | `mempalace_search` | `:1385` | `query` (≤250 chars), `limit?`, `wing?`, `room?`, `max_distance?`, `context?` | `{results: [{drawer_id, wing, room, similarity, content}], query_sanitized, [sanitizer]}` | **Hybrid semantic + BM25 search. Primary read path.** |
| 19 | `mempalace_check_duplicate` | `:1418` | `content`, `threshold?` | `{is_duplicate, matches: [...]}` | Pre-write duplicate check. |
| 20 | `mempalace_add_drawer` | `:1433` | `wing`, `room`, `content`, `source_file?`, `added_by?` | `{success, drawer_id, wing, room}` | **Primary write tool.** Idempotent on deterministic ID. |
| 21 | `mempalace_delete_drawer` | `:1452` | `drawer_id` | `{success, drawer_id}` | Delete drawer (WAL audit trail). |
| 22 | `mempalace_get_drawer` | `:1474` | `drawer_id` | `{drawer_id, content, wing, room, metadata}` | Fetch a drawer. |
| 23 | `mempalace_list_drawers` | `:1487` | `wing?`, `room?`, `limit?`, `offset?` | `{drawers: [...], count, offset, limit}` | Paged listing. |
| 24 | `mempalace_update_drawer` | `:1510` | `drawer_id`, `content?`, `wing?`, `room?` | `{success, drawer_id, wing, room, [noop]}` | Update content and/or location. |
| 25 | `mempalace_diary_write` | `:1538` | `agent_name`, `entry`, `topic?`, `wing?` | `{success, entry_id, agent, topic, timestamp}` | Timestamped agent diary entry → drawer. |
| 26 | `mempalace_diary_read` | `:1005` | `agent_name`, `last_n?`, `wing?` | `{agent, entries: [...], total, showing}` | Read agent diary. |
| 27 | `mempalace_hook_settings` | `:1052` | `silent_save?`, `desktop_toast?` | `{success, settings, [updated]}` | Get/set hook-scripts behavior. |
| 28 | `mempalace_memories_filed_away` | `:1086` | — | `{status, message, count, timestamp}` | Acknowledge latest silent checkpoint. |
| 29 | `mempalace_reconnect` | `:1102` | — | `{success}` | Force palace reconnect (after external modification). |

**Total: 29 tools.** Protocol versions are declared at `mcp_server.py:1600-1604`.

## 3. Memory drawer write path end-to-end (`mempalace_add_drawer`)

Traced from `mempalace_add_drawer` (`mcp_server.py:1433-…` delegating to the internal `tool_add_drawer` at `mcp_server.py:605-660`).

1. **Input validation** (`mcp_server.py:609-613`). `sanitize_name()` (`config.py:19-46`) enforces ≤128 chars, rejects path traversal (`../`, `/`, `\`, null bytes), enforces the regex `^(?:[^\W_]|[^\W_][\w .'-]{0,126}[^\W_])$`. `sanitize_content()` (`config.py:68-76`) enforces ≤100k chars and no null bytes.
2. **Write-ahead log** (`mcp_server.py:628-637` → `_wal_log()` at `mcp_server.py:139-161`). Sensitive keys redacted per `_WAL_REDACT_KEYS` = `{"content", "content_preview", "document", "entry", "entry_preview", "query", "text"}` (`mcp_server.py:134-136`). Entry written to `~/.mempalace/wal/write_log.jsonl` with `O_CREAT|O_WRONLY|O_APPEND` and `0o600` perms (`mcp_server.py:117-131, 155-157`).
3. **Deterministic drawer ID** (`mcp_server.py:620-622`). `drawer_{wing}_{room}_{sha256(wing+room+content)[:24]}` — guarantees idempotent re-writes.
4. **Collection fetch** (`mcp_server.py:623-625`). `_get_collection(create=True)` → `ChromaBackend._client()` → `get_or_create_collection()` (`backends/chroma.py:404-450`). ChromaDB defaults to **cosine HNSW** with all-MiniLM-L6-v2 onnxruntime embeddings.
5. **Idempotency check** (`mcp_server.py:639-644`). `col.get(ids=[drawer_id])`; if present, returns `{success: True, reason: "already_exists"}` without rewriting.
6. **Upsert** (`mcp_server.py:646-662` → `backends/chroma.py:198-205`). Metadata stored (`mcp_server.py:653-660`):
   - `wing`, `room` (required)
   - `source_file` (optional)
   - `chunk_index` (default 0; filled by miners for multi-chunk files)
   - `added_by` (default `"mcp"`)
   - `filed_at` (ISO timestamp)
7. **Cache invalidation** (`mcp_server.py:663`). `_metadata_cache = None` so subsequent `mempalace_status` calls are accurate.

**Chunking at write time:** none. Drawers are stored whole. Chunking into multiple drawers happens at *mining* time in `miner.py` / `convo_miner.py`; each chunk is its own drawer with its own `chunk_index`.

## 4. Knowledge graph (KG) write path

The KG has dedicated MCP tools (`mempalace_kg_add`, `mempalace_kg_invalidate`) — it is **not** implicitly populated by drawer writes.

### Schema (`mempalace/knowledge_graph.py:65-97`)

```sql
CREATE TABLE IF NOT EXISTS entities (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT DEFAULT 'unknown',
  properties TEXT DEFAULT '{}',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS triples (
  id TEXT PRIMARY KEY,
  subject TEXT NOT NULL,
  predicate TEXT NOT NULL,
  object TEXT NOT NULL,
  valid_from TEXT,
  valid_to TEXT,
  confidence REAL DEFAULT 1.0,
  source_closet TEXT,
  source_file TEXT,
  source_drawer_id TEXT,
  adapter_name TEXT,
  extracted_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (subject) REFERENCES entities(id),
  FOREIGN KEY (object) REFERENCES entities(id)
);

CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject);
CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object);
CREATE INDEX IF NOT EXISTS idx_triples_predicate ON triples(predicate);
CREATE INDEX IF NOT EXISTS idx_triples_valid ON triples(valid_from, valid_to);
```

### `kg_add` flow (`mcp_server.py:1222-1248`)

1. Sanitize via `sanitize_kg_value()` / `sanitize_name()` (`config.py:51-65`).
2. `_wal_log("kg_add", …)`.
3. `_kg.add_triple()` (`knowledge_graph.py:148-217`): entity IDs normalized via `_entity_id()` (`:131-132`, lowercased+underscored); entities auto-created; identical-triple check returns existing `triple_id`; else insert.
4. Return `{success, triple_id, fact}`.

### `kg_invalidate` flow (`mcp_server.py:1250-1268` → `knowledge_graph.py:229-237`)

Sets `valid_to` on every matching open-ended triple.

**No automatic KG population from drawer content.** Extractors (`entity_detector.py`, mining time) populate it; not write-time.

## 5. `fact_checker.py` — **VERDICT: NOT WIRED** into the write path

`mempalace/fact_checker.py` exists (336 lines). Exports:

- `check_text(text, palace_path=None, config=None) -> list` (`:52-75`) — returns issues.
- `_check_entity_confusion(text, entity_names_raw)` (`:93-146`) — typo detection.
- `_check_kg_contradictions(text, palace_path)` (`:179-273`) — KG mismatch + stale-fact detection.
- `_edit_distance(s1, s2)` (`:285-303`) — Levenshtein helper.

`fact_checker.py:306-336` wires a `__main__` block for CLI usage.

### Import grep

`rg "from.*fact_checker import|import.*fact_checker" mempalace/` returned only `fact_checker.py:20` itself (a docstring import example). **No other Python module imports it.**

### Call-site grep

- Not called from `mcp_server.py` write handlers.
- Not called from miners (`miner.py`, `convo_miner.py`).
- Not called from KG write tools.
- The only reference elsewhere is a comment at `knowledge_graph.py:397` (`_migrate_schema`) mentioning "ENTITY_FACTS" — dead comment, no active code.

**Conclusion:** `fact_checker.py` is a standalone, CLI-callable validator. Engram can invoke it as a post-write validation step, but cannot rely on MemPalace to run it automatically. The prior Engram design's claim on this point is correct.

## 6. ChromaDB collections and schemas

Palace (`palace.py:53-69`) creates two collections:

### `mempalace_drawers` (primary)

- Document ID pattern: `drawer_{wing}_{room}_{sha256[:24]}`.
- Metadata fields: `wing`, `room`, `source_file`, `chunk_index`, `added_by`, `filed_at`, optional `source_mtime`, `normalize_version` (schema version, `palace.py:50`).
- Vector index: cosine HNSW (ChromaDB default).
- Filterable via where-clauses on `wing`, `room`, `source_file`, `chunk_index`.

### `mempalace_closets` (index / ranking signal)

- Document ID pattern: `closet_{wing}_{room}_{file_hash}_{closet_num:02d}`.
- Document body: newline-separated pointer lines of the form `topic|entities|→drawer_id1,drawer_id2,...` (`palace.py:163-218`).
- Metadata: `source_file`, `wing`, `room`.
- Built by `upsert_closet_lines()` (`palace.py:234-271`) at mining time.
- **Used as a ranking signal only, not a gate** — see §7.

ChromaDB initialization happens in `ChromaBackend.make_client(palace_path)` (`backends/chroma.py:458-500`) using `PersistentClient(path=palace_path)`; stale HNSW segments are quarantined at init.

## 7. Retrieval pipeline end-to-end (`mempalace_search`)

Entry `mcp_server.py:1385-…` → `search_memories()` (`searcher.py:297-400`).

1. **Sanitization.** `sanitize_query(query)` (`query_sanitizer.py`) strips system-prompt contamination; result includes `was_sanitized` + method.
2. **Drawer query (floor).** `col.query(query_texts=[query], n_results=n_results*3)` — always runs; retrieves 3× for re-ranking (`searcher.py:340-365`).
3. **Closet query (signal).** `closets_col.query(query_texts=[query], n_results=n_results*2)`; drawer IDs extracted via regex `→([\w,]+)` (`searcher.py:17,365-390`). Closets **boost ranking only, never hide drawers**.
4. **Hybrid scoring** (`searcher.py:115-147`, `_rerank_by_bm25`). Okapi-BM25 (k1=1.5, b=0.75); vector similarity = `1 - cosine_distance`; combined score `= vector_weight * vec_sim + bm25_weight * norm` (default 0.6/0.4). Sort descending.
5. **Wing/room filter** (`searcher.py:149-159`, `build_where_filter`). ChromaDB where-clause, `{wing: "..."}` or `{$and: [{wing}, {room}]}`.
6. **Neighbor expansion** (`searcher.py:177-237`, optional). For each hit, fetch ±1 sibling chunks from the same `source_file`, combined by `chunk_index`.
7. **Distance threshold** (`searcher.py:308-312`). `distance > max_distance` (default 1.5) → filtered out.
8. **Return shape** (`searcher.py:392-400`):

```json
{
  "results": [
    {"drawer_id": "...", "wing": "...", "room": "...", "similarity": 0.82, "content": "verbatim...", "context": {...}}
  ],
  "query_sanitized": false
}
```

Design property worth preserving in Engram: **recall is gated only by the embedding+BM25 combined score**, never by closet presence. Closets cannot hide a drawer from a search.

## 8. On-disk state

- `~/.mempalace/palace/chroma.sqlite3` — Chroma-managed SQLite with embeddings + metadata.
- `~/.mempalace/palace/{uuid}/` — HNSW segment directories (one per partition).
- `~/.mempalace/knowledge_graph.sqlite3` — KG SQLite (or `{palace_path}/knowledge_graph.sqlite3` when `--palace` is explicit; `mcp_server.py:101`).
- `~/.mempalace/wal/write_log.jsonl` — append-only audit log of writes (`mcp_server.py:123`).
- `~/.mempalace/hook_state/` — hook session-tracking files (`hooks/mempal_save_hook.sh:56`).
- `~/.mempalace/config.json` — optional user config.
- `~/.mempalace/locks/` — cross-process mine lock files (`palace.py:281-285`).

Directories created with `mkdir(parents=True, exist_ok=True)`; WAL + KG dirs try `0o700` where supported (`mcp_server.py:120`, `knowledge_graph.py:56`).

## 9. Hook system

Two shell scripts in `mempalace/hooks/`:

- `mempal_save_hook.sh` (~2.8 KB) — Claude Code **Stop** hook.
- `mempal_precompact_hook.sh` (~7.4 KB) — Pre-compaction state saver.

### `mempal_save_hook.sh`

- Stdin contract (Claude Code): `{session_id, stop_hook_active, transcript_path}`.
- Logic (`hooks/mempal_save_hook.sh:14-195`): count human messages in the JSONL transcript (`:115-132`); track last save per session in `~/.mempalace/hook_state/{SESSION_ID}_last_save` (`:137-146`); if `EXCHANGE_COUNT - LAST_SAVE >= SAVE_INTERVAL` (default 15, `:55`), return a **blocking** decision (`:154`) so the AI runs the diary save.
- Stdout contract: `{"decision": "block", "reason": "..."}` or `{}`.
- Infinite-loop guard: on block, `stop_hook_active=true` on next fire (`:106-110`).
- Optional auto-mine: `mempalace mine "$MINE_DIR"` (`:172`) if `MEMPAL_DIR` is configured.
- Timeout: 30 s.

### `mempal_precompact_hook.sh`

Similar contract, invoked before compaction to snapshot state. Details not fully traced; not load-bearing for Engram.

### Hook direction

Hooks are **one-way: Claude Code → MemPalace**. They are not a plugin system; MemPalace does not register hooks with callers nor emit any callback. A third party (Engram) is free to install additional hooks on its own in `.claude/settings.local.json` (or Codex `hooks.json`) — MemPalace does not interfere.

### Python-side hook contract

None. No plugin registry, no `HookRegistry`, no subclassable callback. This is pure external (shell) integration.

## 10. Observability of writes from an external process — **YES, via the application WAL**

Engram's most important question: can a third-party process observe MemPalace writes without patching internals? Answer: **yes**, with a recommended channel and two fallbacks.

### Primary channel (recommended): `~/.mempalace/wal/write_log.jsonl`

- Defined at `mcp_server.py:117-131`; written to at `:139-161`.
- Append-only JSONL. Each entry:
  ```json
  {
    "timestamp": "2026-04-24T12:34:56.789012",
    "operation": "add_drawer",
    "params": {"drawer_id": "...", "wing": "...", "room": "...", "added_by": "mcp", "content_length": 1234, "content_preview": "[REDACTED 1234 chars]"},
    "result": {"success": true, "drawer_id": "..."}
  }
  ```
- **Operations logged:** `add_drawer`, `delete_drawer`, `update_drawer`, `kg_add`, `kg_invalidate`, `diary_write` (`mcp_server.py:625, 667, 815, 1243, 1264, 959`).
- **Redaction:** content, content_preview, document, entry, entry_preview, query, text (`mcp_server.py:134-136`). Metadata — wing/room/agent/topic — is *not* redacted, which is exactly what Engram needs for anchoring.
- **Permissions:** file `0o600`, dir `0o700`. Owner-only.
- **Atomicity:** `os.open(..., O_WRONLY|O_APPEND|O_CREAT, 0o600)` — crash-safe appends (`mcp_server.py:155-157`).
- **Failure mode:** WAL write error is logged to stderr but the write proceeds anyway (`mcp_server.py:159-161`). Engram must accept the possibility of (rare) missed WAL entries; mitigation in doc 05 is periodic reconciliation against the live Chroma store.

### Secondary channel: ChromaDB SQLite (`~/.mempalace/palace/chroma.sqlite3`)

Direct read of Chroma's internal `embeddings` table. Works but fragile: schema is ChromaDB's internal and may change. Use only to reconcile against WAL, not as a primary event source.

### Tertiary channel: SQLite WAL journal (`chroma.sqlite3-wal`)

Binary, periodically checkpointed away, no application semantics. Not recommended.

### Decision for Engram

Tail `~/.mempalace/wal/write_log.jsonl` with a low-latency file monitor (`watchdog` on macOS/Linux). Parse JSONL, extract `operation` + `drawer_id` + metadata, feed into the Link Layer's event bus (doc 05). Periodically reconcile against Chroma for drift.

## 11. Public Python API & stability

`mempalace/__init__.py:27` declares `__all__ = ["__version__"]`. Only the version string is public. All other modules (`mcp_server`, `cli`, `palace`, `searcher`, …) are considered internal — the convention of `_private` names applies (e.g., `_wal_log`, `_get_collection`).

Stable integration points, by maintainer intent:

1. **MCP surface** (29 tools, §2). Versioned in `SUPPORTED_PROTOCOL_VERSIONS` at `mcp_server.py:1600-1604`.
2. **CLI** (`mempalace mine`, `mempalace search`, …) — documented in `CLAUDE.md`.
3. **`backends/base.py`** — abstract backend interface; third parties can subclass for alternate storage. Cited in README.

## 12. Failure modes

| Scenario | Location | Behavior |
|---|---|---|
| Palace missing | `mcp_server.py:623-625`, `backends/chroma.py:420` | `PalaceNotFoundError`; MCP tools return `{error: "No palace found at ..."}`. |
| SQLite WAL locked | `knowledge_graph.py:122` | `sqlite3.connect(timeout=10)`; exceeds → `OperationalError` → `{success: False, error: str(e)}`. |
| Embedding failure | ChromaDB internals | Exception propagates; MCP tool wraps in try/except → error dict. |
| Disk full on write | `mcp_server.py:646-662` → `:666` | Caught, `{success: False, error: ...}`; SQLite txn guarantees no partial state. |
| WAL write error | `mcp_server.py:159-161` | Logged, operation proceeds. |
| Stale HNSW segment | `backends/chroma.py:52-130` (`quarantine_stale_hnsw`) | If `data_level0.bin` older than sqlite by >1 h, rename segment to `.drift-<ts>`. Wrapped in try/except. |
| Invalid wing/room name | `config.py:19-46` | `ValueError`; returned to caller as `{success: False, error: ...}`. |
| Query too long (>250) | `mcp_server.py:1351` | Rejected at MCP schema validation before handler runs. |

Pattern: **MCP tools return dicts, never raise.** CLI commands print to stderr and `exit(1)`.

## 13. Licensing & deps

- **MIT** (`LICENSE`).
- Core runtime deps: `chromadb>=1.5.4,<2` (Apache 2.0), `pyyaml>=6.0,<7` (MIT), optional `autocorrect>=2.0` (MIT). Full list in `pyproject.toml`.
- Embedding model: **all-MiniLM-L6-v2** via Chroma's default onnxruntime inference. Weights Apache 2.0; runs locally. Model download is an initial one-time network event; all subsequent operations are offline.
- **Zero API key required** for core memory operations — confirmed by absence of API credential requirements in any write path.
- No GPL / AGPL observed in `uv.lock`.

## 14. Implications for Engram (feeds into docs 04, 05, 07, 08)

- **MemPalace is the episodic-memory primitive.** Its MCP surface is complete enough that Engram's `mem.*` namespace is largely proxy pass-through. The one feature *missing* from MemPalace that Engram may want is a "content-based search with an embedded symbol anchor" — this is Engram's value-add and lives in the Retrieval Router (doc 06).
- **Write observability is solid.** The application WAL is the recommended channel for the Link Layer. Doc 05 assumes this and designs polling-based reconciliation as a safety net.
- **KG is a first-class separate surface.** The temporal SQLite KG (`knowledge_graph.py`) is not populated by drawer writes; Engram can treat it as a complementary store to memory. Doc 08 keeps the contradiction-surfacing feature (G-series) because KG data is there — it just isn't auto-populated.
- **`fact_checker.py` is available but inert.** Engram can wrap it as a post-write validator (e.g., invoked on the observed WAL event) without touching MemPalace internals.
- **Hooks are shell-only and unidirectional.** Engram will not rely on MemPalace hooks for its own event bus; it will install its own hooks on Claude Code and tail MemPalace's WAL for memory events.
- **Conflict with Serena's memory tools.** Both upstreams provide memory writes. Doc 07 routes Engram's `mem.*` to MemPalace and leaves Serena's `write_memory` / `read_memory` as legacy proxies with a documented warning.

## Assumptions

- BM25 constants (`k1=1.5, b=0.75`) are read from the agent's investigation; the precise constant values are Okapi defaults and not load-bearing for Engram's router design.
- The `mempal_precompact_hook.sh` detail was not deeply traced; doc 05 does not depend on its internal mechanics.
- Network-free operation depends on the embedding model being pre-downloaded; first-run network behavior is outside MemPalace's direct control.

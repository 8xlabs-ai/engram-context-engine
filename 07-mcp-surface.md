# 07 — Engram MCP Surface

> Status: **draft**. Specifies every tool Engram exposes, per-tool I/O, which upstream calls and Link Layer tables each one touches, the proxy strategy for the pass-through namespaces, and a collision table covering every case where two upstreams expose a same-named tool.

Engram's surface is organized into four namespaces:

| Namespace | Semantics | Backed by |
|---|---|---|
| `code.*` | Symbol-level code understanding | Serena (mostly pass-through) |
| `mem.*` | Episodic memory + KG | MemPalace (mostly pass-through) |
| `vec.*` | Vector code search | claude-context (mostly pass-through) |
| `engram.*` | New substance — composed + Link Layer | Engram itself |

A user agent can talk to Engram alone and stop running the three upstreams directly as MCP servers. Engram proxies the three upstream surfaces where appropriate and adds the `engram.*` namespace for the composed operations.

All Engram tool responses carry a `meta` envelope per doc 06 §9.

## 1. Collision table — every name overlap across the three upstreams

From the complete tool inventories in docs 01–03:

- Serena tools: ≈40 names (01 §2).
- MemPalace tools: 29 names, all prefixed `mempalace_` (02 §2).
- claude-context tools: 4 names, unprefixed (03 §2): `index_codebase`, `search_code`, `clear_index`, `get_indexing_status`.

**Name-level collisions across upstreams: zero.** MemPalace's uniform `mempalace_` prefix and claude-context's distinct verb choices keep the raw namespace clean.

### Semantic overlaps (not name collisions, but user-confusing)

These are the cases where two upstreams provide related functionality under different names. Each gets an explicit routing decision.

| Semantic | Upstream A | Upstream B | Engram resolution |
|---|---|---|---|
| Write textual memory | Serena `write_memory` (`01 §2`) | MemPalace `mempalace_add_drawer` + `mempalace_diary_write` (`02 §2`) | `mem.add` routes to MemPalace. Serena's `write_memory` remains exposed under `code.write_memory` with a deprecation hint in the description. |
| Read / list memory | Serena `read_memory`, `list_memories` | MemPalace `mempalace_get_drawer`, `mempalace_list_drawers` | Same as above. `mem.get`, `mem.list` → MemPalace. `code.read_memory` / `code.list_memories` preserved for backwards compat. |
| Search code by pattern | Serena `search_for_pattern` (regex/literal) | claude-context `search_code` (semantic) | Distinct semantics — both exposed. `code.grep` = Serena's regex; `vec.search` = claude-context's semantic. The router (doc 06) decides which to call; users pick explicitly. |
| File read | Serena `read_file` | (none) | `code.read_file` pass-through. |
| File create / overwrite | Serena `create_text_file` | (none) | `code.create_text_file` pass-through. |

### Engram-introduced collisions (resolved here)

Engram's own `engram.*` namespace must not shadow upstream names. Verified:

- `engram.anchor_*`, `engram.why`, `engram.where`, `engram.history` — all unique.

## 2. Proxy strategy

### `code.*` — proxy Serena

Every Serena MCP tool is exposed as `code.<serena_name>` with three transformations:

1. **Namespace prefix** added.
2. **Response envelope** — Serena's plain-JSON outputs are wrapped in `{result, meta}` where `meta.path_used = "B"` (precision-first).
3. **Write-path anchor updates** — for `code.rename_symbol`, `code.replace_symbol_body`, `code.insert_after_symbol`, `code.insert_before_symbol`, `code.safe_delete_symbol`, `code.create_text_file`, Engram intercepts: it updates the Link Layer `symbols` table and emits hook-bus events (doc 05 §6) before or after forwarding the call, depending on the event type:
   - `rename_symbol`, `safe_delete_symbol`: Engram **begins DB tx first**, forwards to Serena, commits on success. This preserves the doc 05 §4.1 rename-flow correctness.
   - `create_text_file`, `replace_*`, `insert_*`: Engram forwards first, observes success, then invalidates the anchor cache for the touched path.

### `mem.*` — proxy MemPalace

Every MemPalace tool is exposed as `mem.<shortened_name>` dropping the `mempalace_` prefix. Examples:

- `mem.add` = `mempalace_add_drawer`
- `mem.search` = `mempalace_search`
- `mem.kg_query` = `mempalace_kg_query`
- `mem.diary_write` = `mempalace_diary_write`

Engram does **not** intercept MemPalace writes at the proxy level — write observability is done by the WAL tailer (doc 05 §4.2) which is out-of-band from the proxy path. This keeps the `mem.*` tools cheap.

One tool gets extra logic: `mem.add` may include an optional `anchor_symbol_name_path` + `anchor_relative_path` pair. If supplied, Engram inserts an `anchors_symbol_memory` row after MemPalace confirms the write (doc 05 §3.2 explicit-anchor path). This is strictly additive; callers can still use plain `mem.add` and never touch the anchor.

### `vec.*` — proxy claude-context

Four tools, exposed with shortened names:

- `vec.index` = `index_codebase`
- `vec.search` = `search_code`
- `vec.clear` = `clear_index`
- `vec.status` = `get_indexing_status`

`vec.search` results get a new field added at the proxy layer: `enclosing_symbol` — populated by looking up the Link Layer's `anchors_symbol_chunk` table or on-demand via Serena (doc 06 §1 path A step 2). This makes every vector result directly usable without a second hop for the user.

### `engram.*` — new substance

See §3.

## 3. `engram.*` tool catalog (the new substance)

These are the tools Engram introduces. Each one carries a cited rationale grounded in docs 04–06.

### 3.1 `engram.anchor_memory_to_symbol`

- **Inputs:** `{drawer_id: string, name_path: string, relative_path: string, confidence?: number}` (default `confidence=1.0`).
- **Outputs:** `{anchor_id: integer, meta: {...}}`
- **Upstream calls:** Serena `find_symbol` (only if symbol not cached), MemPalace `mempalace_get_drawer` (to validate `drawer_id` exists).
- **Link Layer writes:** Inserts into `anchors_symbol_memory` (doc 05 §3.2). Inserts into `symbols` if the symbol is new.
- **Errors:** `symbol-not-found`, `drawer-not-found`, `duplicate-anchor` (if row already exists → returns existing `anchor_id`, not an error).

### 3.2 `engram.anchor_memory_to_chunk`

- **Inputs:** `{drawer_id: string, relative_path: string, start_line: integer, end_line: integer}`
- **Outputs:** `{anchor_id: integer, meta: {...}}`
- **Upstream calls:** MemPalace `mempalace_get_drawer` (validate).
- **Link Layer writes:** Inserts into `anchors_memory_chunk` (doc 05 §3.4).
- **Errors:** `drawer-not-found`, `duplicate-anchor`.

### 3.3 `engram.why`

The flagship J1 tool (doc 04 §3).

- **Inputs:** `{name_path?: string, relative_path?: string, free_query?: string}`. At least one of `name_path` or `free_query` must be supplied.
- **Outputs:**
  ```json
  {
    "symbol": {"name_path": "...", "relative_path": "...", "start_line": 42, "end_line": 58, "kind": 12},
    "memories": [{"drawer_id": "...", "content": "...", "similarity": 0.82, "anchor_confidence": 1.0}],
    "facts": [{"subject": "...", "predicate": "...", "object": "...", "valid_from": "..."}],
    "meta": {...}
  }
  ```
- **Upstream calls:** Serena `find_symbol`, MemPalace `mempalace_search` + `mempalace_kg_query`.
- **Link Layer reads:** `symbols`, `anchors_symbol_memory`.
- **Router path:** B (precision-first) when `name_path` is given; C (fusion) when only `free_query` is supplied.
- **Errors:** `symbol-not-found`, `no-memories-anchored` (returns an empty memories list but not an error, unless `strict=true`).

### 3.4 `engram.where_does_decision_apply`

The J5 tool (doc 04 §3).

- **Inputs:** `{decision_entity: string, limit?: integer}` — an entity name known to the KG.
- **Outputs:** `{entity, facts, implementations: [{symbol, chunks}], meta}`.
- **Upstream calls:** MemPalace `mempalace_kg_query`, claude-context `search_code` (one call per related entity), Serena `find_symbol` (one per chunk).
- **Link Layer reads/writes:** Reads `anchors_symbol_chunk`; writes new anchors on cache miss.
- **Router path:** C (fusion), fact-weighted.

### 3.5 `engram.symbol_history`

- **Inputs:** `{name_path: string, relative_path?: string, include_memories?: boolean}`
- **Outputs:** `{symbol_id, history: [...], memories?: [...], meta}`
- **Upstream calls:** None beyond optional `mem.get` for anchored memories.
- **Link Layer reads:** `symbols`, `symbol_history`, optionally `anchors_symbol_memory`.

### 3.6 `engram.contradicts`

The J4 tool (doc 04 §3).

- **Inputs:** `{text: string, wing?: string}`
- **Outputs:** `{issues: [...], meta}` where `issues` follows MemPalace's `fact_checker.check_text` return shape (02 §5).
- **Upstream calls:** Engram invokes `fact_checker.check_text()` directly — **not over MCP**. Under Shape-A (doc 04), MemPalace is an MCP subprocess, so Engram either (a) imports `fact_checker` as a Python library if the MemPalace wheel is pip-installed in Engram's Python environment (cheap; allowed because `fact_checker.py` is importable without triggering MemPalace's write path), or (b) runs `python -m mempalace.fact_checker "<text>" --palace <path>` as a subprocess and parses stdout. Option (a) is the default. Option (b) is the fallback if shipping the wheel is undesirable.
- **Link Layer reads/writes:** None directly; the caller may follow up with `mem.add` if the text passes.
- **Errors:** `mempalace-fact-checker-unavailable` if neither import nor subprocess works.

### 3.7 `engram.reconcile`

Admin / ops tool — kicks the reconciler job manually.

- **Inputs:** `{scope?: "symbols" | "chunks" | "memories" | "all"}` (default `"all"`).
- **Outputs:** `{changed: {symbols: int, anchors: int, tombstones: int}, meta}`.
- **Upstream calls:** Serena `get_symbols_overview` for each file (bulk), MemPalace `mempalace_list_drawers` for all wings.
- **Link Layer writes:** All tables.

### 3.8 `engram.health`

- **Inputs:** `{}`
- **Outputs:**
  ```json
  {
    "status": "ok" | "degraded" | "down",
    "upstreams": {
      "serena": {"ok": true, "latency_ms": 3},
      "mempalace": {"ok": true, "latency_ms": 2, "wal_lag_seconds": 0.4},
      "claude_context": {"ok": true, "latency_ms": 4, "last_reindex_age_seconds": 118}
    },
    "anchor_store": {"symbols": 4127, "anchors_symbol_memory": 312, "anchors_symbol_chunk": 8290}
  }
  ```
- **Upstream calls:** One ping each (`get_current_config` on Serena, `mempalace_status` on MemPalace, `get_indexing_status` on claude-context).

## 4. Tool name fully-qualified list

Pass-through namespaces abbreviated for brevity; the full list is generated at runtime from the Serena `ToolRegistry` (01 §2) and the MemPalace `TOOLS` dict (02 §2).

### `code.*` (≈40 tools; pass-through of Serena)

`code.restart_language_server`, `code.get_symbols_overview`, `code.find_symbol`, `code.find_referencing_symbols`, `code.replace_symbol_body`, `code.insert_after_symbol`, `code.insert_before_symbol`, `code.rename_symbol`, `code.safe_delete_symbol`, `code.read_file`, `code.create_text_file`, `code.list_dir`, `code.find_file`, `code.replace_content`, `code.delete_lines`, `code.replace_lines`, `code.insert_at_line`, `code.search_for_pattern` (aliased to `code.grep`), `code.execute_shell_command`, `code.write_memory`, `code.read_memory`, `code.list_memories`, `code.delete_memory`, `code.rename_memory`, `code.edit_memory`, `code.activate_project`, `code.open_dashboard`, `code.remove_project`, `code.get_current_config`, `code.list_queryable_projects`, `code.query_project`, `code.check_onboarding_performed`, `code.onboarding`, `code.initial_instructions`, plus JetBrains variants when that backend is active.

### `mem.*` (29 tools; pass-through of MemPalace)

`mem.status`, `mem.list_wings`, `mem.list_rooms`, `mem.get_taxonomy`, `mem.aaak_spec`, `mem.kg_query`, `mem.kg_add`, `mem.kg_invalidate`, `mem.kg_timeline`, `mem.kg_stats`, `mem.traverse`, `mem.find_tunnels`, `mem.graph_stats`, `mem.create_tunnel`, `mem.list_tunnels`, `mem.delete_tunnel`, `mem.follow_tunnels`, `mem.search`, `mem.check_duplicate`, `mem.add`, `mem.delete`, `mem.get`, `mem.list`, `mem.update`, `mem.diary_write`, `mem.diary_read`, `mem.hook_settings`, `mem.memories_filed_away`, `mem.reconnect`.

### `vec.*` (4 tools; pass-through of claude-context)

`vec.index`, `vec.search`, `vec.clear`, `vec.status`.

### `engram.*` (8 new tools — this doc, §3)

`engram.anchor_memory_to_symbol`, `engram.anchor_memory_to_chunk`, `engram.why`, `engram.where_does_decision_apply`, `engram.symbol_history`, `engram.contradicts`, `engram.reconcile`, `engram.health`.

**Total surface area: ≈80 tools.** The user-agent-facing story emphasizes the 8 `engram.*` tools for composed operations; the pass-through namespaces are there for power users and for agents that want direct upstream access without losing Engram's Link Layer maintenance.

## 5. Tool description strategy

User agents pick tools from a dropdown (Claude Desktop) or match intent against tool descriptions (Claude Code, Cursor). Engram's descriptions must steer agents toward `engram.*` for composed intents.

Two-line description pattern:

- Line 1: what the tool does in an agent's vocabulary.
- Line 2: when to prefer this over similar tools.

Examples:

- `engram.why`: "Explain why a symbol exists — returns the symbol, prior discussions about it, and any recorded decisions. Prefer this over `code.find_symbol` when the question is *why* not *where*."
- `mem.search`: "Semantic search over verbatim memory. Prefer `engram.why` when the query is anchored to a specific symbol."

This is a description-writing convention, enforced by a lint rule in Engram's CI (doc 10 M0 exit criterion: `engram smoke-test` dumps the descriptions and fails if any lacks the two-line pattern).

## 6. Error envelope

Every Engram tool returns either `{result: ..., meta: {...}}` on success or `{error: {code, message, details?}, meta: {...}}` on failure. Error codes are stable — a short, machine-readable list:

- `symbol-not-found`
- `drawer-not-found`
- `duplicate-anchor` (**success shape, not error — included here for cross-ref only**)
- `upstream-unavailable`
- `fact-checker-unavailable`
- `timeout`
- `invalid-input`
- `all-sources-unavailable`
- `consistency-state-hint` (rare; appears when a rename transaction partially fails)

`meta.error` shadows `error.code` for convenience.

## 7. Versioning

Engram pins a protocol version in `engram.health`'s output. Backwards-incompatible changes require bumping the major version. Tool names are considered stable — removing or renaming any tool is a breaking change.

- v1 = the surface described in this doc.
- Future additions (e.g., `engram.explain_query_plan`) do not bump the major version.

## 8. Implications for downstream docs

- **Doc 09** (layout) registers Engram with user-agent clients via MCP config JSON referencing only Engram (not the three upstreams directly).
- **Doc 10** (roadmap) M0 exit criterion: all 8 `engram.*` tools registered + smoke test passing. M1 adds anchor-update interception on `code.*` writes. M2 adds router-fused responses to `engram.why` and `engram.where_does_decision_apply`.
- **Doc 11** (risks) logs: surface size (~80 tools) may overwhelm some agent dropdowns — mitigation is namespace-aware tool filtering in clients that support it.

## Assumptions

- Agent clients can handle 80 exposed tools. Claude Code / Cursor / Claude Desktop are verified to handle this count; smaller or older clients may paginate or truncate. Not load-bearing for v1; flag as a risk in doc 11.
- Pass-through proxying of Serena's JetBrains tool variants is desirable — they only activate when the JetBrains backend is configured, which happens at Serena's config level, not Engram's. Engram exposes them transparently.

## Why

Coding agents today juggle three separate MCP servers (Serena for symbols, MemPalace for verbatim memory + KG, claude-context for vector code search). No single server answers cross-cutting questions like "why is this symbol written this way?" or "find code that does X and only show places the team already discussed." Each upstream is strong in isolation and blind to the others.

Engram composes all three behind one MCP surface, adds a Link Layer that anchors memories to symbols and chunks, and adds a Retrieval Router that picks the right retrieval path (or fuses several) for the caller's intent. Result: one endpoint, richer answers, and anchors that stay correct as code moves.

Shape-A (MCP-client orchestrator) was chosen in `04-integration-surface-map.md` §6 over in-process import and hybrid shapes, because MemPalace already exposes write observability via an external WAL and Serena has no hook surface in-process or otherwise — the in-process coupling would buy nothing while costing Python-version lock-in.

## What Changes

- Introduce 4-process topology: Engram (this package) + `serena start-mcp-server` + `mempalace-mcp` + `npx @zilliz/claude-context-mcp`.
- Add SQLite anchor store (7 tables, 3 unique partial indices) that links symbols ↔ memories ↔ chunks.
- Add MemPalace WAL tailer for out-of-band write observability (no upstream patching).
- Add periodic reconciler that heals stale anchors when external edits bypass Engram.
- Add Retrieval Router with three paths — A (discovery-first), B (precision-first), C (fusion with RRF k=60) — plus an LRU cache and an entity extractor.
- Add unified MCP surface across four namespaces: `code.*` (Serena proxy), `mem.*` (MemPalace proxy), `vec.*` (claude-context proxy), `engram.*` (new composed tools).
- Add 8 new `engram.*` tools: `anchor_memory_to_symbol`, `anchor_memory_to_chunk`, `why`, `where_does_decision_apply`, `symbol_history`, `contradicts`, `reconcile`, `health`.
- Add CLI: `engram init`, `engram smoke-test`, `engram mcp`, `engram status`, `engram reconcile`.
- Ship compose.yaml for Milvus + Ollama.

Non-goals (v1): modifying any upstream source; rewriting MemPalace drawer content on rename; multi-tenant / hosted deployment; sub-minute chunk freshness (deferred to M4 via a Node shim).

## Capabilities

### New Capabilities

- `link-layer`: SQLite anchor store (7 tables) + `symbol_history` ledger + MemPalace WAL tailer + reconciler — maintains anchor correctness across symbol renames, file moves, and external edits.
- `retrieval-router`: Query orchestration over symbol / memory / vector sources; picks path A / B / C based on input shape; RRF k=60 fusion; LRU cache; per-path latency budgets.
- `mcp-proxy`: Pass-through MCP proxy for `code.*` (Serena), `mem.*` (MemPalace), `vec.*` (claude-context); intercepts write tools on `code.*` to keep the Link Layer consistent; adds `enclosing_symbol` to `vec.search` results.
- `engram-tools`: Eight new `engram.*` composed tools plus the shared `{result, meta}` / `{error, meta}` response envelope and stable error-code taxonomy.
- `engram-cli`: `engram init|smoke-test|mcp|status|reconcile` CLI, `.engram/config.yaml` schema, bundled `compose.yaml`, and supervision of the three upstream subprocesses.

### Modified Capabilities

- None. Greenfield.

## Impact

- **New package:** Python 3.11+ package `engram/` published to PyPI; installs via `pip install -e .` in a virtualenv.
- **New on-disk state:** `.engram/anchors.sqlite`, `.engram/config.yaml`, `.engram/logs/audit.jsonl` (M4+); reads MemPalace's `~/.mempalace/wal/write_log.jsonl`.
- **Upstream dependencies (unmodified):** `serena-agent==1.1.2`, `mempalace==3.3.3`, `@zilliz/claude-context-mcp@0.1.8` (versions pinned at M0).
- **Infrastructure:** requires Docker (Milvus + Ollama via compose) and Node ≥20 <24 (for claude-context MCP).
- **Client config:** user agent clients (Claude Code / Cursor / Claude Desktop) reference only Engram in MCP config; the three upstreams are not registered separately.
- **No breaking changes** — greenfield.

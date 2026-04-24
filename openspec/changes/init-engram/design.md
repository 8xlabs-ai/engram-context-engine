## Context

Three mature open-source MCP servers already solve parts of the coding-agent retrieval problem: Serena (LSP symbols), MemPalace (verbatim memory + temporal KG), and claude-context (vector code search). Each is best-of-breed in its lane and completely blind to the others. A user agent wiring all three in parallel gets more tools but not more answers — cross-cutting queries ("why is `Foo.process` written this way?") require manual orchestration every time.

The full investigation lives in the planning bundle (`engram/00-README.md` through `12-glossary.md`, ~27.9k words). This design is the compressed form.

Upstreams (cited in docs 01–03 with `repo:line` anchors):

- **Serena** — Python 3.11+, ≈40 MCP tools, no external hook surface, no file-watch (`restart_language_server` exists because external edits go unnoticed).
- **MemPalace** — Python 3.9+, 29 MCP tools, append-only WAL at `~/.mempalace/wal/write_log.jsonl` with full write observability, `fact_checker.py` importable but not wired to writes.
- **claude-context** — TypeScript / Node 20+, 4 MCP tools, Merkle-DAG incremental index on a 5-minute tick, no push notifications.

The brief forbids modifying upstream code. Integration must be via public MCP surfaces, the MemPalace WAL, and importable Python modules only.

## Goals / Non-Goals

**Goals:**

- One MCP endpoint (Engram) that downstream agents can register instead of three.
- Link Layer that keeps symbol ↔ memory ↔ chunk anchors correct across Engram-initiated renames, with bounded-staleness recovery for external edits.
- Retrieval Router that picks the right path per query shape and fuses multi-source results with RRF k=60.
- Stable, versioned MCP surface (≈80 tools) with a documented error envelope.
- Mechanical exit criteria per milestone (no vibes-based "it works").

**Non-Goals:**

- Modifying Serena, MemPalace, or claude-context source. (Optional upstream PRs in M4 are additive and non-blocking.)
- Rewriting MemPalace drawer content on rename — MemPalace is verbatim; Engram tracks entity renames in KG with `valid_to`, never edits drawers.
- Multi-workspace federation (deferred to M5).
- Hosted LLM summarization (cut as G20; reintroduce only on user demand).
- Sub-minute chunk freshness in v1 — the 5-minute Merkle tick is accepted; sub-minute deferred to M4 via a chokidar + core-JS Node shim.

## Decisions

### D1. Shape-A: MCP-client orchestrator (not in-process import)

**Chosen:** Engram runs as a Python MCP server; internally it is an MCP *client* to three subprocess MCP servers (Serena, MemPalace, claude-context).

**Alternatives considered:**
- **Shape-B — Python-core + claude-context subprocess.** Import Serena and MemPalace in-process; only claude-context stays external. Rejected: in-process buys no observability MemPalace's WAL doesn't already give, and it locks Engram to Python 3.11+ to satisfy Serena's minimum.
- **Shape-C — hybrid.** Mix-and-match per upstream. Rejected: extra shape complexity for no concrete gain given D1's analysis.

**Rationale:** MemPalace WAL provides complete write observability externally. Serena has no hook surface at all (in-process or otherwise) so wrapping at the Engram dispatch layer is identical under both shapes. MCP stdio cost is ~1 ms/round-trip, negligible next to 50–200 ms tool work.

### D2. Anchor store = SQLite, single-writer, WAL-mode

7 tables — `symbols`, `symbol_history`, `drawers`, `chunks`, `anchors_symbol_memory`, `anchors_symbol_chunk`, `anchors_memory_chunk` — with 3 unique partial indices preventing duplicate anchors.

**Alternatives:** Postgres (overkill for single-workspace local-first), JSONL (no indexed reads), Redis (not durable without AOF + loses transactional rename).

### D3. WAL tailer (not in-process hooks) for MemPalace writes

Engram tails `~/.mempalace/wal/write_log.jsonl` with a persisted cursor stored in `.engram/state/wal_cursor.json`. Read lag budget: 2 s in `engram.health`.

**Alternatives:** MemPalace `backends/base.py` plugin (allowed, but changes state path and breaks user continuity); polling drawer list on a timer (cheap but lossy).

### D4. Retrieval Router paths

- **Path A (discovery-first):** `vec.search` → resolve to symbols → optional memory filter. Used for free-text queries.
- **Path B (precision-first):** Serena `find_symbol` → anchored memories → KG facts. Used when caller supplies `name_path`.
- **Path C (fusion):** run all three in parallel, combine with RRF k=60, cap at K=20. Used when caller supplies both a symbol and a free query, or when an `engram.*` composed tool is called.

**Fusion algorithm:** Reciprocal Rank Fusion with k=60. Standard, score-scale agnostic, no training. Fixture unit tests provide expected fused order.

### D5. Upstream-rename flow (symbol↔memory anchor correctness)

1. Engram begins SQLite transaction on `symbols` + `anchors_symbol_memory`.
2. Engram forwards to Serena `rename_symbol`.
3. On Serena success, Engram updates `symbols.name_path` in place, appends to `symbol_history` with `change_kind='rename'`, and commits.
4. Engram inserts KG triple `(old_name, renamed_to, new_name, valid_from=now)` via MemPalace `kg_add` and invalidates prior identity facts with `kg_invalidate` (`valid_to=now`). Drawers are never rewritten.
5. On Serena failure, Engram rolls back; `consistency-state-hint` is returned for client awareness.

External (non-Engram-initiated) renames are caught by the reconciler within the 24 h window (or 5 min with M4 shim).

### D6. Process supervision

`engram init` writes a user-level supervisor unit (`launchctl` on darwin, `systemd --user` on linux) that manages the three upstream subprocesses. `engram mcp` is the foreground MCP server exposed to the client; it relies on the supervisor to have already started the upstreams. Each upstream crash is isolated — `engram.health` reports per-upstream liveness and latency.

### D7. MCP surface shape

- `code.*` proxies every Serena tool 1:1 with a namespace prefix, a `{result, meta}` envelope, and write-path interception for `rename_symbol`, `safe_delete_symbol`, `replace_symbol_body`, `insert_before_symbol`, `insert_after_symbol`, `create_text_file`.
- `mem.*` drops the `mempalace_` prefix and proxies 1:1; `mem.add` optionally accepts `anchor_symbol_name_path` + `anchor_relative_path` to write one `anchors_symbol_memory` row after MemPalace confirms.
- `vec.*` shortens the 4 claude-context tools (`index`, `search`, `clear`, `status`); `vec.search` adds an `enclosing_symbol` field resolved from the Link Layer or on-demand via Serena.
- `engram.*` is the only non-pass-through namespace — 8 new composed tools (§ specs).

Collision analysis: zero raw-name collisions across the three upstreams. Semantic overlaps (memory write, code search) are disambiguated by tool descriptions; Serena's memory tools stay behind `code.write_memory` etc. with a deprecation hint.

### D8. Error envelope and code taxonomy

Stable error codes: `symbol-not-found`, `drawer-not-found`, `upstream-unavailable`, `timeout`, `invalid-input`, `fact-checker-unavailable`, `all-sources-unavailable`, `consistency-state-hint`. `duplicate-anchor` is a success shape (returns existing `anchor_id`), not an error.

Every response: `{result, meta}` or `{error: {code, message, details?}, meta}`. `meta.path_used` ∈ {A, B, C} for router responses; `meta.cache` ∈ {hit, miss}; `meta.latency_ms` always present.

## Risks / Trade-offs

- **R1 — claude-context 5-min tick bounds anchor freshness on the chunk side.** → Mitigation: accept for v1; M4 Node shim (chokidar + `Context.reindexByChange()`) for sub-minute sync. Optional upstream PR-CC-1 adds a `sync_now(path)` MCP tool.
- **R2 — External-source rename invisibility.** If a developer edits via IDE save with no hook or via `git pull`, anchors go stale until reconciler runs. → Mitigation: 24 h reconcile window is the soft upper bound; `engram.reconcile --scope all` is callable on demand; staleness surfaced via `engram.health`.
- **R3 — `fact_checker.py` dormant in upstream.** Engram invokes it out-of-band. If MemPalace later wires `fact_checker` into its write path, `engram.contradicts` will double-check. → Mitigation: version-detect on startup and stop wrapping if MemPalace now runs it natively.
- **R4 — Serena memory tools vs. MemPalace memory tools.** Both write memory-like state to different stores. → Mitigation: `mem.*` routes to MemPalace (authoritative); Serena's `write_memory`/`read_memory` stay under `code.*` with deprecation hints in the tool description.
- **R5 — Python packaging + Node subprocess.** Engram's Python wheel has to manage a Node subprocess for claude-context. → Mitigation: `engram init` hard-requires Node 20 ≤ v < 24 and fails loudly with a fix-me message if absent.
- **R6 — Surface size (≈80 tools) may overwhelm older clients.** → Mitigation: namespace-aware filtering in clients that support it; tool descriptions steer agents toward `engram.*` for composed intents.
- **R7 — MCP stdio transport adds ~1 ms/roundtrip.** → Mitigation: within doc 06 latency budgets; cache layer (LRU) sits between router and the upstream clients.

## Migration Plan

No migration — this is greenfield. Users who currently register Serena / MemPalace / claude-context separately in their MCP client config replace the three entries with a single Engram entry on install. The three upstreams still work standalone; Engram is additive.

## Open Questions

- **Q-04-SHAPE.** Re-open Shape Decision if a <50 ms end-to-end bound materializes, or if a Serena extension that demands `Tool` subclassing by Engram appears.
- **Q-05-WAL-ROTATION.** MemPalace has no WAL rotation policy (`mempalace/mempalace/mcp_server.py`, no rotate/truncate/rollover logic). Default assumption: append-only-forever. File upstream question about expected growth and rotation plan.
- **Q-07-DESCRIPTION-LINT.** Exact regex for the two-line description pattern used by the CI lint is TBD — proposed: first line ≤ 120 chars imperative; second line starts with "Prefer " or "Use when ".
- **Q-10-VERSION-PINS.** Upstream minor bumps during M0–M3 re-tested against exit criteria. Policy for accepting a bump (patch = auto, minor = review, major = new change proposal) to be codified.

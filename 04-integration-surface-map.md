# 04 — Integration Surface Map

> Status: **draft**. This doc maps what each upstream answers well vs. poorly, names the join points where two or three composed beats any one alone, and closes with the **Shape Decision** now that the evidence from docs 01–03 is in.

Every claim is grounded in the cited inventories; inline citations point at `01-upstream-inventory-serena.md` / `02-…-mempalace.md` / `03-…-claude-context.md` which in turn carry the `repo:line` citations.

## 1. What each upstream is actually good for

### Serena — precise, symbol-level code understanding (the "precision" primitive)

- **Strengths.** LSP-grade symbol lookup (`find_symbol` — 01 §2), cross-file references (`find_referencing_symbols`), atomic symbol-level edits (`rename_symbol`, `replace_symbol_body`, `safe_delete_symbol`). Project-path validation, `.gitignore`-aware listing, robust LSP crash recovery (01 §9).
- **Weaknesses.** Natural-language search is limited to `search_for_pattern` (literal/regex, not semantic). No ranking beyond grep-like ordering. No observability of external file edits (01 §8) — no filesystem watcher, no event bus. `restart_language_server` exists precisely because external edits go unnoticed.
- **Data exposed.** Per-symbol location `(relative_path, start_line, end_line, kind, name_path)`, reference lists, file contents.
- **Hooks exposed.** None externally. In-process Python subclassing of `Tool` / `Hook` is the only extension path. No pubsub, no callback registry (01 §5).
- **Unique capability.** The only primitive that answers "find every reference to symbol X across the project with LSP-grade accuracy."

### MemPalace — verbatim episodic memory + temporal KG (the "memory" primitive)

- **Strengths.** Verbatim, lossless storage (02 §3). Hybrid BM25 + cosine retrieval with closet-based ranking signals (02 §7). Explicit temporal KG with `valid_from`/`valid_to` triple timestamps (02 §4). Zero outbound network after initial model download. Crash-safe append-only WAL at `~/.mempalace/wal/write_log.jsonl` with full write observability to a third party (02 §10).
- **Weaknesses.** No code-aware chunking (treats code as text). `fact_checker.py` is not wired in — contradiction detection is a post-write opt-in (02 §5). KG is not auto-populated from drawer writes; triples are explicit.
- **Data exposed.** Drawers (content + wing/room/metadata), triples `(subject, predicate, object, valid_from, valid_to)`, palace graph (tunnels between wings).
- **Hooks exposed.** Claude-Code-style shell hooks in `hooks/` (unidirectional, CC → MemPalace). Pluggable `backends/base.py` for swapping storage, but no in-process event callback registry (02 §9).
- **Unique capabilities.** Verbatim storage — the only primitive in the trio that can return *your exact prior words*. Temporal facts — the only one with explicit `valid_to` stale-fact handling.

### claude-context — AST-chunked vector code search (the "discovery" primitive)

- **Strengths.** Tree-sitter AST chunking over 10 languages (03 §3), five embedding providers including fully local Ollama (03 §4), Milvus-backed dense search with cosine HNSW (03 §5). Self-hosted Milvus fully supported (03 §9). Merkle-DAG incremental re-index (03 §6).
- **Weaknesses.** Incremental re-index runs on a **5-minute tick** with no file-watch or git-hook (03 §6 verdict). Chunks carry `(relativePath, startLine, endLine, language)` metadata but **not** the enclosing function/class name (03 §3). TypeScript-only consumption from Python; no Python binding (03 §13).
- **Data exposed.** Per-chunk `(content, relativePath, startLine, endLine, language, score)`. Per-codebase snapshot at `~/.context/mcp-codebase-snapshot.json`, file-hash Merkle snapshot at `~/.context/merkle/<md5>.json`.
- **Hooks exposed.** None. Uniquely, no subclass/callback surface either — integration is MCP protocol or core-JS import only.
- **Unique capability.** Broad fuzzy "find me code that does X" over natural-language queries across a whole repo.

## 2. What each upstream is bad at (and therefore why Engram is needed)

| Need | Serena | MemPalace | claude-context | Who's missing? |
|---|---|---|---|---|
| Natural-language code search | ❌ grep only | ❌ not code-aware | ✅ |  |
| Exact symbol resolution | ✅ |  |  |  |
| Cross-file references | ✅ |  |  |  |
| Verbatim prior conversation recall |  | ✅ |  |  |
| Temporal facts about people / decisions |  | ✅ |  |  |
| "Where in code does this memory apply?" | partial | ❌ | ❌ | **join — Engram** |
| "Why is this symbol the way it is? (decisions)" | ❌ | partial | ❌ | **join — Engram** |
| "Find me similar code that had a prior bug fix" | ❌ | ❌ | ✅ but context-blind | **join — Engram** |
| Contradiction detection across memory | ❌ | inert (02 §5) | ❌ | **gap — Engram wraps** |
| Near-real-time anchor freshness on renames | polling | WAL tail | 5-min tick | **gap — Engram** |

The last three rows are where Engram justifies its existence.

## 3. Join points — where 2 or 3 composed beats any one alone

A "join point" is a query that a user would plausibly ask a coding agent which requires primitives from at least two upstreams, invoked in a specific order, and whose value is strictly larger than the best single-upstream answer. For each join below, the upstream calls are cited against the inventories.

### J1 — "Why is `foo.py:process_batch` written this way?"

- **Step 1 (precision):** Serena `find_symbol` (01 §2) on `name_path_pattern="process_batch"` in `foo.py` → returns body + location.
- **Step 2 (memory):** MemPalace `mempalace_search` (02 §2, entry #18) using the symbol body as query, filtered on a `project` wing → returns verbatim prior conversations mentioning this function.
- **Step 3 (KG):** MemPalace `mempalace_kg_query` with entity = the symbol's name_path or a known decision ID → returns any facts (e.g., "decided_to_batch_by: 100 rows").
- **Value:** answers a "why" question that no single upstream can. Serena gives the *what*, MemPalace gives the *rationale*.
- **Feasibility:** all three primitives exist and are MCP-callable.

### J2 — "Find code that does X, and only show me places where the maintainers already discussed X"

- **Step 1 (discovery):** claude-context `search_code` (03 §2) with the natural-language query → top-K chunks.
- **Step 2 (precision):** Serena `find_symbol` to resolve each chunk to its enclosing symbol (since chunks don't carry this — 03 §3 explicit gap). Requires `relative_path` + line number lookup.
- **Step 3 (memory):** For each resolved symbol, MemPalace `mempalace_search` with the symbol's name_path. Keep only chunks with ≥1 relevant memory hit.
- **Value:** vector search alone returns too many code hits. Filtering by "someone discussed this" dramatically sharpens results for trust-sensitive work.
- **Feasibility:** all three primitives exist; Engram must do the symbol-name lookup between step 1 and 2 (the Link Layer's `symbol↔chunk` anchor in doc 05 caches this).

### J3 — "Rename `Foo.process` to `Foo.run` and update all memories and KG facts that reference it"

- **Step 1 (precision):** Serena `rename_symbol` (01 §2) → atomic LSP rename across the codebase.
- **Step 2 (Link Layer update):** Engram updates every `symbol↔memory` and `symbol↔chunk` anchor that pointed to the old name (doc 05).
- **Step 3 (memory):** For each anchored memory, Engram does **not** rewrite drawer content (MemPalace is verbatim — 02 §14) but records an entity rename in KG via `mempalace_kg_add` with `valid_from=now` for the new fact and `mempalace_kg_invalidate` for the old.
- **Value:** keeps code, memory pointers, and KG view-of-world coherent across a rename without rewriting verbatim memories.
- **Feasibility:** all primitives exist; the Engram-side anchor update is the new substance.

### J4 — "What contradicts this new memory I'm about to write?"

- **Step 1 (memory):** Engram observes the incoming write via its own MCP tool wrapper (no upstream hook — 02 §9 confirms MemPalace emits no callbacks).
- **Step 2 (contradiction check):** Engram invokes `fact_checker.check_text()` (02 §5, available but inert) directly (MemPalace's `fact_checker.py` is importable via CLI or in a Python-embedded configuration; in the MCP-client shape it is invoked by Engram's own Python code).
- **Step 3 (user surfacing):** Engram returns a warning envelope to the caller *before* the write lands in MemPalace, or after with an "undo" pointer to the observed drawer_id.
- **Value:** repairs the main gap identified in 02 §5 — contradiction detection is dormant in MemPalace.
- **Feasibility:** `fact_checker.py` exports `check_text` (02 §5 cites `mempalace/fact_checker.py:52-75`). Engram invokes it out-of-band.

### J5 — "Find every place a prior architectural decision is implemented"

- **Step 1 (KG):** MemPalace `mempalace_kg_query` for the decision entity → returns triples (e.g., `decision_x decided_for component_y`).
- **Step 2 (discovery):** claude-context `search_code` on each resulting component name → chunks.
- **Step 3 (precision):** Serena `find_symbol` to resolve chunks into canonical symbols + full context.
- **Value:** closes the loop from a human-language decision entity to concrete code, via the structured KG in between. No single upstream does this.

### J6 — "Show me the time evolution of how people talked about this symbol"

- **Step 1 (precision):** Serena resolves the symbol's `name_path`.
- **Step 2 (memory over time):** MemPalace `mempalace_search` + `mempalace_diary_read` (02 §2 entries #18, #26) with the symbol name; results are already timestamped in their drawer metadata.
- **Step 3 (KG timeline):** MemPalace `mempalace_kg_timeline` for the symbol entity → ordered facts with `valid_from`/`valid_to`.
- **Value:** a temporal view onto a single symbol that combines unstructured chat + structured facts.

These six joins are *not* the exhaustive list; they are the ones most cited in the prior design's G-series features. Doc 08 walks G1–G22 explicitly and cites which join(s) each feature uses.

## 4. Matrix — hooks, data, and fit

| Dimension | Serena | MemPalace | claude-context |
|---|---|---|---|
| Language | Python 3.11+ | Python 3.9+ | TypeScript / Node 20+ |
| Install | `uv pip install serena-agent` | `pip install mempalace` | `npx @zilliz/claude-context-mcp` |
| MCP surface | ≈30 tools (01 §2) | 29 tools (02 §2) | 4 tools (03 §2) |
| Python import surface | Limited (no `__all__`; 01 §3) | Only `__version__` (02 §11) | None |
| Write observability | Wrap tool calls; no external event | **WAL at `~/.mempalace/wal/write_log.jsonl`** (02 §10) | None externally; core JS API for sync |
| File-watch | None (01 §8) | n/a — not file-sourced | Polling 5 min (03 §6) |
| On-disk state | `.serena/` + `~/.serena/` (01 §4) | `~/.mempalace/` (02 §8) | `~/.context/` + Milvus (03 §10) |
| License | MIT | MIT | MIT |
| Failure style | Log-and-continue, LSP auto-restart (01 §9) | Dicts not exceptions (02 §12) | Log-and-continue (03 §11) |

## 5. Risks this map surfaces

- **R-04.1 — claude-context freshness.** 5-minute tick bounds anchor freshness on the chunk side. Mitigation: Engram installs its own file watcher OR runs a thin Node shim that calls `Context.reindexByChange()` out-of-band (03 §14). Logged in doc 11.
- **R-04.2 — Serena memory tools vs. MemPalace.** Both write memories. Collision handled in doc 07 (routing); user-facing story must not lose track of which memory store is authoritative. Recommended: Engram's `mem.*` namespace targets MemPalace; Serena's `write_memory`/`read_memory` remain available under `code.memory_*` for legacy reasons but carry a deprecation hint in the tool description.
- **R-04.3 — `fact_checker.py` remains out-of-band.** Contradiction detection is an Engram-side invocation. If MemPalace later wires `fact_checker` into its own write path, Engram's J4 flow needs to adapt to avoid double-checking.
- **R-04.4 — External-source rename invisibility.** If a developer edits / moves a file outside any Engram-observed path (IDE save with no hook, git pull, etc.), anchors go stale until a polling reconciliation catches them. This is a soft correctness property, not a hard one; doc 05 bounds the stale window.

## 6. Shape Decision

The user deferred this decision to the investigation (see plan file). The evidence from docs 01–03 is sufficient to make it now.

### Options recap

- **Shape-A — MCP-client orchestrator.** Engram is a Python MCP server exposed to user agents. Internally it is an MCP *client* to three subprocesses: `serena start-mcp-server`, `mempalace-mcp`, and `npx @zilliz/claude-context-mcp`.
- **Shape-B — Python core + claude-context subprocess.** Engram imports Serena and MemPalace in-process (they are Python); only claude-context runs as an MCP subprocess.
- **Shape-C — hybrid driven per-upstream by what hooks exist.** Mix-and-match.

### Decision: **Shape-A (MCP-client orchestrator)**.

### Rationale

The original case for Shape-B was "in-process hooks give the strongest observability on write-heavy Python stores." The inventories show this advantage is illusory:

- **MemPalace already exposes full write observability externally** via the application WAL (02 §10). Tailing `~/.mempalace/wal/write_log.jsonl` gives Engram every write with metadata, a redaction-respecting payload, and atomic append semantics. In-process import would not give Engram *more* information — it would give the same information with a larger coupling surface.
- **Serena has no hook surface at all** — in-process or otherwise (01 §5, §8). The only way Engram learns about a Serena-side change is by being the one calling the tool. This is true identically for Shape-A and Shape-B: wrap the Engram-side tool dispatch, not Serena itself.
- **Shape-B introduces a Python-version coupling** that Shape-A avoids. Serena requires Python ≥3.11; MemPalace supports ≥3.9. Engram under Shape-B must pick 3.11+. Shape-A keeps Engram's own interpreter version decoupled from upstream choices.
- **Shape-B forbids the one case where in-process would matter** — patching upstream internals — because the brief explicitly forbids modifying upstream code.
- **MCP transport cost is ~1 ms per stdio round trip**, negligible next to the 50–200 ms actual tool work.
- **Operational simplicity.** Shape-A makes Engram's process topology explicit: four long-lived processes (Engram + three upstreams), uniform MCP, uniform logging. Crash of any one upstream is isolated.

### What Shape-A specifically implies for later docs

- **Doc 05** (Link Layer) treats MemPalace write events as an external WAL-tail stream, not a Python callback. The Serena side is updated synchronously inside Engram's own tool dispatch. The claude-context side is updated via periodic reconciliation *plus* an optional Node shim for sub-minute freshness.
- **Doc 06** (Retrieval Router) composes MCP calls, not Python function calls. Cache keys include tool name + args; cache layer sits between router and the three subprocess MCP clients.
- **Doc 07** (MCP surface) is a pure proxy + router for pass-through namespaces. The `engram.*` namespace is the only one without pass-through semantics.
- **Doc 08** (feature mapping) can keep features whose observability requirement is "Engram initiates the write" or "tail WAL"; it must cut or polling-ify features that need "observe arbitrary third-party writes to Serena's memory dir" (none of the 22 features in the prior design actually requires this — see doc 08).
- **Doc 09** (layout) ships process-management in `engram init`: write a `launchctl` / systemd unit or a simple supervisor script that manages the three upstream subprocesses.
- **Doc 10** (roadmap) M0 delivers the four-process topology + health check. M1 adds the Link Layer. M2 adds the Router. M3 adds J-family features. M4 adds the Node shim for claude-context sub-minute sync (only if measured benefit).

### Fallback triggers for re-opening the decision

If one of the following is discovered later, re-visit Shape-A:

- A bounded-latency requirement (< 50 ms end-to-end) that MCP stdio overhead breaks. Current target budgets (doc 06) are comfortable at stdio cost.
- A Serena extension that demands `Tool` subclassing by Engram (e.g., Engram wants to add a Serena-native tool). This would be a new PR upstream rather than a shape change.
- Python packaging constraints that make managing a Node subprocess untenable. Mitigation is a PyPI wheel that ships a small Node runtime; not a shape change.

**Shape-A is the default for the rest of this bundle.** Open question Q-04-SHAPE in doc 11 allows the user to overrule.

## 7. What this map does NOT answer (open for later docs)

- Exact Link Layer schema and anchor-kind population (doc 05).
- Exact fusion algorithm for the Retrieval Router's three-way-join path (doc 06).
- Per-tool collision resolution in the unified MCP surface (doc 07).
- Which of G1–G22 survive (doc 08).

## Assumptions

- "MCP stdio overhead ~1 ms per round trip" is an empirical ballpark; not measured against these specific three upstreams. If doc 06's performance analysis shows otherwise, the Shape Decision gets a second look.
- The pluggable `backends/base.py` in MemPalace (02 §11) is not used by Engram in Shape-A. If a future Engram feature needs a bespoke backend, Shape-B becomes attractive again for that one upstream.

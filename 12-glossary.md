# 12 — Glossary

> Status: **draft**. Precise meanings for terms used across the Engram bundle. When a term is used in two different senses upstream (Serena vs. MemPalace vs. claude-context), the entry says so and pins the Engram meaning.

---

**AAAK** — MemPalace's compression dialect for the index layer. Compact symbolic format scanned by an LLM to locate drawers without reading full contents (02 CLAUDE.md). Engram does not consume AAAK directly; it calls MemPalace's MCP tools which read the AAAK index internally.

**Anchor** — A row in the Engram Link Layer that associates two addresses from different upstreams: a symbol, a memory drawer, and/or a code chunk. Three anchor kinds: `symbol↔memory`, `symbol↔chunk`, `memory↔chunk` (doc 05 §2). Anchors carry `confidence` and `created_by` for auditability.

**Anchor kind** — One of the three shape categories for anchors. Implemented as three SQL tables in the anchor store (`anchors_symbol_memory`, `anchors_symbol_chunk`, `anchors_memory_chunk`).

**Anchor store** — The SQLite database at `.engram/anchors.sqlite` that materializes the Link Layer. Owned by Engram, not by any upstream. Schema in doc 05 §2.

**Backend (MemPalace)** — A pluggable storage interface declared in `mempalace/backends/base.py` (02 §11). ChromaDB is the default. Engram consumes MemPalace over MCP in Shape-A; does not implement a custom backend.

**Chunk** — A vector-indexed slice of code produced by claude-context's AST chunker (03 §3). Identified by `(relative_path, start_line, end_line, language)`. Carries embedded content + metadata in Milvus. **Not** the same as a Serena symbol — a chunk may contain one symbol, part of one, or several. A chunk also differs from a MemPalace *drawer*, which is a verbatim text snippet.

**claude-context (or CC)** — The Zilliz OSS project at `claude-context/`. A TypeScript/Node MCP server providing tree-sitter AST chunking + Milvus-backed vector code search (doc 03).

**Closet (MemPalace)** — An index layer document whose body points at drawer IDs by topic (02 §6). Acts as a ranking signal for search, never a gate. Engram does not touch closets directly.

**Collection (vector)** — A Milvus table of vectors. Each claude-context-indexed codebase gets its own collection, named `code_chunks_<md5(path)>` (03 §5). Engram does not create collections; claude-context manages them.

**Collection (memory)** — A ChromaDB collection inside a MemPalace palace. MemPalace creates `mempalace_drawers` (primary) and `mempalace_closets` (index) (02 §6).

**Confidence** — A `REAL` column on `anchors_symbol_memory` in `[0, 1]` (doc 05 §2). 1.0 for explicit anchors, 0.5 for router-inferred, decays over time if the reconciler cannot verify (doc 08 G16).

**Decision (KG entity)** — An entity in MemPalace's knowledge graph that represents a concrete choice ("decision_x decided_for component_y"). Used by J5 / G8 to link to implementing code. Not a first-class type in MemPalace — represented as any other entity (02 §4).

**Drawer** — A MemPalace unit of verbatim content storage. Identified by a deterministic `drawer_{wing}_{room}_{sha256[:24]}` ID (02 §3). Stored whole (no automatic write-time chunking). Lives in a wing + room.

**Drift event** — A reconciler-emitted event when Engram's anchor store and live upstream state disagree. Examples: a drawer in `anchors_symbol_memory` no longer exists in MemPalace; a chunk anchor's line range no longer matches Serena's symbol location. Drift events cause anchor invalidation or confidence decrement (doc 05 §5).

**Engram** — This system. The composed MCP substrate defined across docs 00–12. Not yet implemented; this bundle is the design.

**Engram tool** — An MCP tool in the `engram.*` namespace (doc 07 §3). Distinct from pass-through tools in `code.*` / `mem.*` / `vec.*`.

**Entity (KG)** — A node in MemPalace's SQLite knowledge graph (02 §4). Lowercased-normalized-ID, e.g. `amr_zaghloul`. Used as subject or object of triples.

**Fact** — A triple `(subject, predicate, object, valid_from, valid_to)` in MemPalace's knowledge graph (02 §4). Can have `valid_to = NULL` (current) or a timestamp (invalidated). Not the same as a *drawer*; facts are structured, drawers are verbatim text.

**File path conventions** — All paths in Engram's anchor store are project-relative, forward-slash, normalized by `engram.util.normalize_path`. Absolute paths never stored (doc 05 §2).

**Fusion (retrieval)** — The act of combining ranked result lists from two or three upstreams into one. In Engram, this means Reciprocal Rank Fusion with `k=60` (doc 06 §2).

**Hook (MemPalace)** — A shell script in `mempalace/hooks/` invoked by Claude Code at lifecycle events (02 §9). Engram does not use MemPalace hooks as an event source; it tails the WAL instead.

**Hook bus (Engram)** — In-process pub/sub inside Engram, carrying events like `symbol.renamed`, `memory.written`, `chunk.generation_advanced` (doc 05 §6). Consumed by the router cache invalidator and the reconciler. Not a cross-process event system.

**Hybrid search** — A retrieval mode that combines dense (vector) and sparse (BM25) scoring. MemPalace's search is hybrid natively (02 §7). claude-context can do hybrid if opted into, but the default MCP path is dense-only (03 §5).

**Index generation** — A monotone integer on chunk anchor rows (`anchors_symbol_chunk.index_generation`, doc 05 §2) marking which claude-context re-index tick the anchor was created during. Incremented by the cc-reconciler. Used to detect anchors older than the stale-window budget.

**J1–J6** — The six named join points in doc 04 §3. Each is a query pattern that composes two or three upstreams. J1 is "why is this symbol like this?", J2 is discovery→precision, J3 is rename propagation, J4 is contradiction check, J5 is decision→code, J6 is temporal view.

**KG** — Knowledge graph. In Engram, always refers to MemPalace's SQLite-backed temporal KG (02 §4), not to anything Engram stores itself.

**Link Layer** — The first new piece of substance Engram adds: the anchor store + the population / reconciliation machinery that keeps it correct (doc 05).

**LSP (Language Server Protocol)** — The protocol Serena uses to talk to language servers like pyright, fortls, etc. Engram does not speak LSP; it talks to Serena over MCP, which speaks LSP to the language servers (01 §1).

**Meta envelope** — The `meta` field on every Engram MCP response, carrying `path_used`, `path_degraded`, `sources_used`, `cache_hits`, `latency_ms`, `error` (doc 06 §9). Always present; downstream agents can inspect without error.

**Memory (MemPalace)** — A drawer. "Memory" and "drawer" are interchangeable in Engram docs; we prefer "drawer" when speaking of the MemPalace ID, "memory" when speaking of the abstract concept.

**Memory (Serena)** — A markdown file under `.serena/memories/` or `~/.serena/memories/global/` (01 §4). Distinct from a MemPalace drawer. Engram's `mem.*` namespace targets MemPalace; Serena's memory tools remain under `code.*` with a deprecation hint (doc 07 §1).

**Name path (Serena)** — A dotted/slash-delimited path to a symbol, e.g. `Foo/process` or `MyClass.bar.inner` (01 §2). The primary human-readable identity for a symbol. **Not** stable across renames — Engram's Link Layer uses an internal `symbol_id` that follows a symbol across renames (doc 05 §2).

**On-disk state (Engram)** — `.engram/anchors.sqlite` + `.engram/logs/` + `.engram/config.yaml` at the workspace root. All user-only permissioned (doc 09 §9).

**Palace** — The MemPalace data root at `~/.mempalace/palace/` (or a `--palace` override). Contains ChromaDB state + KG SQLite. One palace per user by default (02 §8).

**Path A / B / C** — The three Retrieval Router paths (doc 06 §1). A = discovery-to-precision (vec → symbol → memory). B = precision-first (symbol → references). C = fusion (all three).

**Precision-first** — See Path B. A query where the user already has a symbol identity.

**Provenance** — In Engram's response envelopes, the source of each data field (e.g., "this chunk came from vec", "this symbol came from code", "this decision came from mem"). Carried as `meta.sources_used` (doc 06 §9).

**Proxy (namespace)** — In Engram's MCP surface, a pass-through tool that forwards to an upstream with minor transformations (doc 07 §2). `code.*`, `mem.*`, `vec.*` are proxy namespaces. `engram.*` is not.

**RRF (Reciprocal Rank Fusion)** — The rank-fusion algorithm Engram uses for Path C: `fused_score(d) = Σ 1 / (k + rank_i(d))` with `k=60` (doc 06 §2).

**Reconciler** — The Engram worker that periodically walks upstream state to catch drift the WAL tailer and Engram-rename wrapper missed. Daily full scan in v1; incremental is a scope-cut for monorepos (doc 05 §5, doc 08 G-row for Q-11).

**Relative path** — Project-relative, forward-slash-normalized. See "File path conventions."

**Room (MemPalace)** — A time- or topic-based subdivision of a wing. Holds drawers (02 CLAUDE.md).

**Router** — See "Retrieval Router."

**Retrieval Router** — The second new piece of substance Engram adds: the query orchestrator that picks one of three paths, calls the appropriate upstreams, fuses, and returns (doc 06).

**Serena** — The Oraios-AI OSS project at `serena/`. An MCP-based Python toolkit with LSP-backed symbol tools (doc 01).

**Shape (integration)** — One of three ways Engram composes the upstreams: A (MCP-client orchestrator), B (Python core + claude-context subprocess), C (hybrid). Doc 04 §6 chose A.

**Snapshot (claude-context)** — A JSON file at `~/.context/mcp-codebase-snapshot.json` tracking which codebases are indexed and their status (03 §10).

**Merkle snapshot (claude-context)** — A per-codebase file at `~/.context/merkle/<md5>.json` holding SHA-256 hashes of every indexed file, used for change detection (03 §6).

**Stale window** — The bounded time window during which an anchor may disagree with live upstream state. Per anchor kind in doc 05 §5.3.

**Symbol** — In Engram, always a Serena symbol: something LSP can point at (function, class, method, top-level variable). Identified by `(relative_path, name_path, kind)` at query time; by internal `symbol_id` in the anchor store. **Not** the same as a chunk.

**Symbol ID** — Engram's internal, stable integer identifier for a symbol. Persistent across renames (doc 05 §2). Implementation detail — not surfaced in MCP responses.

**Symbol history** — The append-only table `symbol_history` in the anchor store, recording every rename / move / creation / deletion (doc 05 §2). Enables "did you mean X?" replies for stale references.

**Tombstone** — A non-NULL `tombstoned_at` on a `symbols` row (doc 05 §2). The symbol no longer exists per Serena but its history and anchors are preserved.

**Tool marker (Serena)** — A mixin class controlling tool visibility and routing (01 §5). Examples: `ToolMarkerOptional`, `ToolMarkerBeta`, `ToolMarkerCanEdit`.

**Triple** — A KG row `(subject, predicate, object, valid_from, valid_to)` (02 §4). Engram does not invent new triples automatically; users or composed flows do so via `mem.kg_add`.

**Tunnel (MemPalace)** — An explicit cross-wing link between rooms (02 §2 entry #14). Used by J-adjacent memory traversals. Engram exposes these as `mem.create_tunnel` / `mem.follow_tunnels`.

**Upstream** — One of Serena / MemPalace / claude-context. Not modified by Engram; consumed via MCP (plus an optional Python import of MemPalace's `fact_checker` in doc 07 §3.6).

**User agent** — The AI coding agent (Claude Code, Cursor, Claude Desktop, etc.) that connects to Engram's MCP server and issues tool calls. See "MCP client" in the MCP spec.

**Verbatim** — MemPalace's non-negotiable guarantee: stored memory is byte-identical to the original text (02 CLAUDE.md). Engram inherits this — `engram.*` tools never paraphrase or summarize drawer content.

**WAL (write-ahead log)** — Two distinct usages:
1. **MemPalace application WAL** at `~/.mempalace/wal/write_log.jsonl`. Append-only JSONL, redacted. Engram's primary memory-event source (02 §10).
2. **SQLite WAL mode** — the WAL journal mode used by ChromaDB's internal SQLite and by Engram's own `anchors.sqlite`. Engram does not tail SQLite WALs directly.

**Wing (MemPalace)** — Top-level palace subdivision for a person, project, or topic. Contains rooms (02 CLAUDE.md).

**Workspace** — The user's project root that Engram is configured to operate on. Identified by `ENGRAM_WORKSPACE` env var or CWD + `.engram/config.yaml` (doc 09 §5).

---

## Abbreviations

- **CC** — claude-context
- **KG** — Knowledge graph
- **LSP** — Language Server Protocol
- **MCP** — Model Context Protocol
- **MP** — MemPalace
- **RRF** — Reciprocal Rank Fusion
- **WAL** — Write-ahead log

# 08 — Feature Mapping (G1–G22 → Engram)

> Status: **draft**. Walks the 22 features from the prior Engram design and, for each, produces: true upstream dependencies (cited), Link Layer tables read/written, missing primitives + mitigation, revised S/M/L complexity, and an explicit **keep / cut / defer** recommendation grounded in docs 01–06.

**Legend.**
- **S** ≤ 1 engineer-week • **M** = 1–3 weeks • **L** = 3–6 weeks.
- **Keep** = v1. **Defer** = v1.1+ (M4–M5 in doc 10). **Cut** = dropped pending re-validation.

The prior design defined G1–G22 without reading the code. Many S/M/L estimates changed after docs 01–03 exposed actual upstream surfaces. Each row names the specific reason a downgrade or upgrade happened.

## Summary

| Verdict | Count | Features |
|---|---|---|
| **Keep (v1)** | 12 | G1, G2, G3, G4, G5, G6, G8, G9, G10, G11, G12, G14 |
| **Defer** | 6 | G7, G13, G15, G16, G19, G22 |
| **Cut** | 4 | G17, G18, G20, G21 |

Rationale tables per feature below.

---

## G1 — Symbol-move handler

**Prior intent.** Maintain anchor correctness across symbol renames and moves.

- **Upstream deps:** Serena `rename_symbol` (01 §2), file-tool wrappers (01 §2).
- **Missing primitive:** external event for rename/move done outside Engram. Serena has no observer (01 §8). **Mitigation:** Engram wraps its own tool dispatch (doc 05 §4.1); developer-originated renames reconciled within the 24 h reconcile window (or 5 min with M4 watcher).
- **Link Layer:** writes `symbols`, `symbol_history`; invalidates `anchors_symbol_memory`, `anchors_symbol_chunk`.
- **Complexity prior → now:** M → **M** (unchanged).
- **Verdict:** **Keep.** The workspace stays consistent for Engram-initiated renames; external-source staleness is bounded and documented (doc 05 §5.3). M1 scope.

## G2 — Symbol↔memory anchor

**Prior intent.** Link drawers to symbols so "why is `Foo` like this" returns discussion context.

- **Upstream deps:** Serena `find_symbol`, MemPalace `mempalace_add_drawer`, `mempalace_get_drawer`, `mempalace_search`.
- **Missing primitive:** none.
- **Link Layer:** `anchors_symbol_memory`, `symbols`.
- **Complexity prior → now:** M → **S**. Simpler than estimated because the WAL tailer already surfaces writes (02 §10); the explicit `engram.anchor_memory_to_symbol` tool is a thin wrapper.
- **Verdict:** **Keep.** Core v1 feature; M1 scope.

## G3 — Incremental re-index on file save

**Prior intent.** Keep vector chunks fresh as code changes, without full re-index.

- **Upstream deps:** claude-context `reindexByChange()` at the core-JS level (03 §6).
- **Missing primitive:** file-watch or git-hook integration. claude-context does **not** emit change events; it does a 5-minute Merkle poll (03 §6 verdict).
- **Mitigation options:**
  - (a) Accept the 5-minute tick for v1. **Verdict: Keep (limited).** Anchor invalidation at tick granularity is fine for Retrieval Router budgets (doc 06 §7).
  - (b) M4: ship a Node shim that wraps `Context.reindexByChange()` with a chokidar watcher for sub-minute sync. **Verdict: Defer to M4.**
- **Link Layer:** writes `anchors_symbol_chunk`, `meta.claude_context_index_generation`.
- **Complexity prior → now:** S → **M** (was underestimated; the Node shim adds work).
- **Verdict:** **Keep (5-min default), defer faster sync to M4.**

## G4 — Anchor-aware search (Retrieval Router Path C)

**Prior intent.** Fuse vector + memory + KG retrieval.

- **Upstream deps:** all three; covered in doc 06.
- **Missing primitive:** none; fusion algorithm specified (RRF k=60).
- **Link Layer:** reads all anchor tables.
- **Complexity prior → now:** L → **M**. Lower because RRF is a well-known algorithm and the upstreams all return ranked lists.
- **Verdict:** **Keep.** M2 scope.

## G5 — Contradiction surfacing (J4)

**Prior intent.** Warn when a new memory contradicts existing KG / prior drawers.

- **Upstream deps:** MemPalace `fact_checker.py` exists but is NOT wired to writes (02 §5). `mempalace_kg_query`.
- **Missing primitive:** none — `fact_checker.check_text()` is importable (02 §5).
- **Mitigation:** Engram's `engram.contradicts` tool invokes it directly (doc 07 §3.6).
- **Link Layer:** none — the check is against MemPalace's own state.
- **Complexity prior → now:** L → **S**. Much simpler than estimated — the hard part already exists in MemPalace (02 §5) and just needs to be called.
- **Verdict:** **Keep.** M3 scope. First time the world sees `fact_checker` doing something useful.

## G6 — "Why" composed tool (J1)

**Prior intent.** Single-call explanation of a symbol's prior context.

- **Upstream deps:** Serena `find_symbol`, MemPalace `mempalace_search`, `mempalace_kg_query`.
- **Missing primitive:** none.
- **Link Layer:** reads `anchors_symbol_memory`, `symbols`, `symbol_history`.
- **Complexity prior → now:** M → **M** (unchanged).
- **Verdict:** **Keep.** The flagship. M2 scope.

## G7 — Graph visualization

**Prior intent.** Interactive UI showing anchors, wings, and symbol relationships.

- **Upstream deps:** MemPalace `mempalace_graph_stats` + tunnels (02 §2); local anchor tables.
- **Missing primitive:** UI framework in scope.
- **Complexity prior → now:** L → **L**. UI design is out of scope per the brief.
- **Verdict:** **Defer.** Not M0–M3; revisit at M5.

## G8 — Where-does-decision-apply (J5)

**Prior intent.** From a KG decision entity, surface implementing code.

- **Upstream deps:** MemPalace `mempalace_kg_query`, claude-context `search_code`, Serena `find_symbol`.
- **Missing primitive:** none.
- **Link Layer:** reads `anchors_symbol_chunk`; writes on cache miss.
- **Complexity prior → now:** M → **M**.
- **Verdict:** **Keep.** M3 scope.

## G9 — Temporal view (J6)

**Prior intent.** How talk about a symbol evolved over time.

- **Upstream deps:** Serena `find_symbol`, MemPalace `mempalace_diary_read`, `mempalace_search`, `mempalace_kg_timeline`.
- **Missing primitive:** none.
- **Link Layer:** reads `anchors_symbol_memory`, `symbols`.
- **Complexity prior → now:** M → **S**. Each upstream already returns timestamped data; Engram merges.
- **Verdict:** **Keep.** M3 scope.

## G10 — Verbatim retention guarantee

**Prior intent.** Never summarize or lossy-compress memories.

- **Upstream deps:** MemPalace's own design principle (02 CLAUDE.md non-negotiable).
- **Missing primitive:** none — MemPalace already guarantees it.
- **Link Layer:** none.
- **Complexity prior → now:** S → **S**. Engram's job is to *not* add a compression step.
- **Verdict:** **Keep.** This is really a "do not do X" feature — v1 scope by default.

## G11 — Self-hosted / offline operation

**Prior intent.** Zero outbound network after setup.

- **Upstream deps:** MemPalace (offline-capable with ONNX embedder — 02 §13), claude-context with Ollama + self-hosted Milvus (03 §9), Serena (Python-only, no required outbound).
- **Missing primitive:** bundled Milvus compose file. Not in claude-context (03 §9). **Mitigation:** Engram's doc 09 ships a `compose.yaml`.
- **Link Layer:** none.
- **Complexity prior → now:** M → **M**.
- **Verdict:** **Keep.** M0 scope (smoke-tested as part of initial setup).

## G12 — Unified MCP surface

**Prior intent.** One MCP server for user agents to talk to.

- **Upstream deps:** all three.
- **Missing primitive:** none; doc 07 specifies.
- **Link Layer:** orthogonal.
- **Complexity prior → now:** M → **M**.
- **Verdict:** **Keep.** M0 scope.

## G13 — Query plan explainer (`engram.explain_query_plan`)

**Prior intent.** Show the user which upstreams answered which part of a fused result.

- **Upstream deps:** none beyond what `engram.why` / `engram.where...` already compute.
- **Missing primitive:** none — every Engram tool already returns `meta.path_used` + `meta.sources_used` (doc 06 §9).
- **Link Layer:** none.
- **Complexity prior → now:** M → **S**. Purely a rendering layer.
- **Verdict:** **Defer.** Nice-to-have; M5. The meta envelope already provides enough signal.

## G14 — Cross-wing memory joins (MemPalace tunnels)

**Prior intent.** Follow tunnels between wings to surface related memories across projects.

- **Upstream deps:** MemPalace `mempalace_traverse`, `mempalace_follow_tunnels`, `mempalace_find_tunnels` (02 §2).
- **Missing primitive:** none — MemPalace already supports this.
- **Link Layer:** none.
- **Complexity prior → now:** M → **S**. Pass-through + slight adaptation of the response shape.
- **Verdict:** **Keep.** M2 scope. Exposed under `mem.traverse`, `mem.follow_tunnels`.

## G15 — Decision-diagram authoring UI

**Prior intent.** UI to author KG facts from conversation snippets.

- **Upstream deps:** MemPalace `mempalace_kg_add` + user-agent tool calls.
- **Missing primitive:** UI (out of scope per brief).
- **Complexity prior → now:** L → **L**.
- **Verdict:** **Defer.** Not v1.

## G16 — Confidence-decayed anchors

**Prior intent.** Stale anchors degrade instead of disappearing.

- **Upstream deps:** none.
- **Missing primitive:** none — anchor table has `confidence` column (doc 05 §2).
- **Link Layer:** reads/writes `anchors_symbol_memory.confidence`.
- **Complexity prior → now:** S → **S** (reconciler lowers confidence on soft mismatches).
- **Verdict:** **Defer to M4.** v1 uses 1.0 / 0.5 fixed confidences; decay is additive.

## G17 — Automatic KG population from drawer writes

**Prior intent.** Every `mempalace_add_drawer` spawns KG extraction.

- **Upstream deps:** MemPalace's `entity_detector.py` (internal, called at mining time, not write time — 02 §4).
- **Missing primitive:** write-time extractor. MemPalace's design is explicitly "KG is not auto-populated from drawer writes" (02 §4). Auto-populating contradicts MemPalace's design principle.
- **Link Layer:** writes would cascade.
- **Complexity prior → now:** L → **cut**.
- **Verdict:** **Cut.** Engram will NOT auto-populate KG; users or Engram's composed flows (J5, G8) can call `mem.kg_add` explicitly. Re-evaluate at M5 only if user data shows compelling need.

## G18 — Claude Code hook takeover

**Prior intent.** Engram replaces MemPalace's `mempal_save_hook.sh` + `mempal_precompact_hook.sh` with Engram-managed equivalents that do more.

- **Upstream deps:** MemPalace hooks are shell scripts (02 §9).
- **Missing primitive:** none, but taking over hooks conflicts with MemPalace's own lifecycle expectations.
- **Complexity prior → now:** M → **cut**.
- **Verdict:** **Cut.** MemPalace's hooks are narrowly scoped and doing their job. Engram installs *additional* hooks if needed (non-conflicting) but does not replace MemPalace's.

## G19 — Multi-workspace federation

**Prior intent.** One Engram instance across multiple projects with per-workspace anchor stores.

- **Upstream deps:** all three support multi-project (Serena `list_queryable_projects`, MemPalace wings, claude-context per-codebase collections).
- **Missing primitive:** federation layer in Engram.
- **Complexity prior → now:** L → **L**.
- **Verdict:** **Defer.** M5. v1 is single-workspace.

## G20 — Hosted LLM summarization of search results

**Prior intent.** Agent calls Engram; Engram calls an LLM to summarize across upstreams.

- **Upstream deps:** none; would add LLM dependency.
- **Missing primitive:** LLM integration.
- **Complexity prior → now:** M → **cut**.
- **Verdict:** **Cut.** Violates G10 (verbatim retention) in spirit — if the user wants summarization, their agent does it. Engram returns structured results, not prose.

## G21 — Benchmarks / eval harness

**Prior intent.** Quantitative quality metrics.

- **Upstream deps:** all three, plus a benchmark corpus.
- **Missing primitive:** corpus design, labeler tooling.
- **Complexity prior → now:** L → **cut**.
- **Verdict:** **Cut.** Per brief: benchmarks are explicitly out of scope for this plan.

## G22 — Enterprise audit log

**Prior intent.** Every Engram tool call + provenance logged tamper-evidently.

- **Upstream deps:** MemPalace already has WAL for its side (02 §10); Engram would add one for the `engram.*` namespace.
- **Missing primitive:** none — small JSONL append.
- **Complexity prior → now:** M → **S**.
- **Verdict:** **Defer to M4.** Not needed for v1 single-user; trivial to add later.

---

## Keep / defer / cut traceability table

| Feature | Verdict | Reason (grounded in 01–06) | Milestone |
|---|---|---|---|
| G1 — Symbol-move handler | Keep | Serena write-path wrapping is sufficient (01 §8, doc 05 §4.1) | M1 |
| G2 — Symbol↔memory anchor | Keep | MemPalace WAL + explicit tool is enough (02 §10, doc 07 §3.1) | M1 |
| G3 — Incremental re-index | Keep (tick) / Defer (watcher) | claude-context polls at 5 min (03 §6); faster sync is a Node shim | M2 / M4 |
| G4 — Anchor-aware search | Keep | RRF k=60 specified (doc 06 §2) | M2 |
| G5 — Contradiction surfacing | Keep | `fact_checker.check_text` already importable (02 §5) | M3 |
| G6 — Why composed tool | Keep | All primitives exist (doc 04 §3 J1) | M2 |
| G7 — Graph visualization | Defer | UI out of scope | M5 |
| G8 — Decision → code | Keep | All primitives exist (doc 04 §3 J5) | M3 |
| G9 — Temporal view | Keep | All primitives timestamp-carrying (doc 04 §3 J6) | M3 |
| G10 — Verbatim retention | Keep | No-op for Engram; MemPalace guarantees | M0 (inherited) |
| G11 — Self-hosted / offline | Keep | Needs bundled Milvus compose (doc 09) | M0 |
| G12 — Unified MCP surface | Keep | Doc 07 specifies | M0 |
| G13 — Query plan explainer | Defer | Meta envelope already has the data (doc 06 §9) | M5 |
| G14 — Cross-wing tunnels | Keep | Pass-through of MemPalace primitives (02 §2) | M2 |
| G15 — Decision-diagram UI | Defer | UI out of scope | M5 |
| G16 — Confidence-decayed anchors | Defer | v1 uses fixed confidences; decay additive (doc 05 §3.2) | M4 |
| G17 — Auto-populate KG | Cut | Contradicts MemPalace design (02 §4) | — |
| G18 — Hook takeover | Cut | MemPalace hooks are narrow and correct (02 §9) | — |
| G19 — Multi-workspace federation | Defer | v1 is single-workspace | M5 |
| G20 — Hosted LLM summarization | Cut | Violates G10 in spirit | — |
| G21 — Benchmarks | Cut | Per brief, out of scope | — |
| G22 — Enterprise audit log | Defer | Trivial to add later | M4 |

## Net effect on milestone planning (input to doc 10)

- **M0 (4–5 eng-weeks):** G11, G12 (+setup scaffolding).
- **M1 (3–4 eng-weeks):** G1, G2 (Link Layer + WAL tailer + Engram-rename wrapper).
- **M2 (4–5 eng-weeks):** G3 (5-min tick path), G4, G6, G14.
- **M3 (3–4 eng-weeks):** G5, G8, G9 (feature flowering on top of Router + Link Layer).
- **M4 (2–3 eng-weeks):** G3 watcher, G16, G22.
- **M5 (open-ended):** G7, G13, G15, G19, and anything that turned up during user feedback.

Total M0–M3: **14–18 engineer-weeks** for the v1 core. Doc 10 makes these commitments sharp with exit criteria.

## Assumptions

- G3's Node shim at M4 is a small (~100 LOC) TypeScript file that exports one function calling `Context.reindexByChange()`. If claude-context's core API changes between 0.1.8 and when M4 lands, the shim's LOC estimate grows.
- G17 cut is final unless MemPalace itself wires `fact_checker` into the write path (02 §5 verdict). If that happens upstream, G17 reopens as free-to-implement.
- Engram-weeks are calibrated against a mid-senior Python engineer with MCP familiarity. Two-engineer teams can probably parallelize M1 and M2.

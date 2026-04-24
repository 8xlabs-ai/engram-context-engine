# 10 — Phased Roadmap (M0–M5)

> Status: **draft**. Each milestone names: scope, engineer-week estimate, exit criteria as mechanical checks, and any upstream PRs that must land.

**Totals.** v1 (M0–M3) is **14–18 engineer-weeks** calibrated for a mid-senior Python engineer with MCP familiarity. M4 is an additional **2–3 weeks**. M5 is open-ended and user-demand-driven.

Team sizing: 1 engineer full time can ship M0–M3 in about 4 months. 2 engineers in parallel can compress to 2.5 months (M1 and M2 parallelize well).

---

## M0 — Shell + topology

**Scope.** Engram package scaffolding. Four-process topology (Engram + three upstream MCP subprocesses). Config file. `engram init` / `engram smoke-test` / `engram mcp` / `engram status` CLIs. Bundled compose file. Unified MCP surface with proxy-only namespaces — no Link Layer yet, no router, no `engram.*` tools other than `engram.health`.

**Features:** G11, G12 (doc 08).

**Engineer-weeks:** 4–5.

**Exit criteria (mechanical).**

1. `pip install -e .` succeeds in a clean virtualenv with Python 3.11.
2. `engram init --embedding-provider Ollama` in an empty git repo creates `.engram/config.yaml` and `.engram/anchors.sqlite`, exits 0.
3. `docker compose -f engram/deploy/compose.yaml up -d` reports `milvus-standalone` and `ollama` healthy within 60 s.
4. `engram smoke-test` returns exit 0 after:
   - pinging all three upstreams,
   - running `vec.index` on `tests/fixtures/sample_workspace/` and waiting for `status="completed"`,
   - calling `engram.health` and asserting `status=="ok"`.
5. `engram mcp` starts a server that, when connected from a bare MCP client, lists exactly the tool set specified in doc 07 §4 (80 tools) — verified by `jq 'length'` on the tools/list response.
6. Running the Engram tool description linter (doc 07 §5) over the registered tools passes (every `engram.*` tool has the two-line description pattern).

**Upstream PRs required:** none.

---

## M1 — Link Layer + write observability

**Scope.** The anchor store (SQLite with the schema from doc 05 §2). WAL tailer for MemPalace (doc 05 §4.2). Engram-rename wrapper that updates `symbols` + `symbol_history` transactionally (doc 05 §4.1). Hook bus (doc 05 §6). Explicit anchor tools `engram.anchor_memory_to_symbol`, `engram.anchor_memory_to_chunk`.

**Features:** G1, G2.

**Engineer-weeks:** 3–4.

**Exit criteria.**

1. DB has the 7 tables + 3 unique partial indices exactly as doc 05 §2 specifies — verified by `sqlite3 .engram/anchors.sqlite '.schema'` matching a fixture.
2. `engram.anchor_memory_to_symbol(drawer_id=D, name_path=N, relative_path=P)` inserts one row into `anchors_symbol_memory` and one row into `symbols` if absent. Re-calling is a no-op (unique-index idempotent).
3. Triggering `code.rename_symbol` via MCP results in: `symbols.name_path` updated, a new `symbol_history` row appended, AND Serena's `rename_symbol` returning success — all inside one Engram response — verified by a pytest fixture that reads the DB after the call.
4. Writing a drawer via `mem.add` causes a matching entry in `.engram/anchors.sqlite`-associated state or (baseline) the WAL event is observed within 2 s — verified by an end-to-end test that writes a drawer and waits on `meta.wal_lag_seconds == 0` in `engram.health`.
5. `engram.health` reports `wal_lag_seconds` and `anchor_store.symbols` / `anchors_symbol_memory` counts.

**Upstream PRs required:** none. (Serena has no hook surface but Engram-initiated writes require no upstream change; MemPalace's WAL is already a stable contract.)

---

## M2 — Retrieval Router + Path C fusion

**Scope.** Router with classifier (doc 06 §3), three paths (doc 06 §1), RRF fusion (doc 06 §2), LRU cache (doc 06 §5), entity extractor (doc 06 §4). `engram.why` and `engram.symbol_history`. On-demand symbol↔chunk resolution (doc 05 §3.3 lazy path). Pass-through namespaces remain; router composes them.

**Features:** G3 (tick path), G4, G6, G9, G14.

**Engineer-weeks:** 4–5.

**Exit criteria.**

1. `engram.why({"name_path": "Foo/process", "relative_path": "src/foo.py"})` against `tests/fixtures/sample_workspace/` returns a response with non-empty `symbol` and `memories` fields when the fixture is pre-populated with two anchored drawers.
2. Path-classifier unit tests cover all 7 rows of doc 06 §3's decision table with ≥95% pass.
3. RRF fusion unit test: given three fixture source lists with known ranks, the fused order matches a hand-computed expected.
4. P50 latency on the sample workspace (~2k chunks, ~20 symbols, ~5 drawers): path A ≤ 150 ms warm, path B ≤ 100 ms warm, path C ≤ 300 ms warm — measured with `pytest-benchmark` and committed baselines in `tests/integration/benchmarks/`.
5. Cache LRU test: second identical call hits the cache; invalidation on `symbol.renamed` event evicts matching entries (fixture-verified).
6. `mem.traverse` pass-through returns identical output to calling `mempalace_traverse` directly, byte-for-byte except for the `meta` envelope — golden-file test.

**Upstream PRs required:** none.

---

## M3 — Feature flowering (J4, J5)

**Scope.** `engram.contradicts` (J4) invoking MemPalace's `fact_checker.check_text` as an in-process import. `engram.where_does_decision_apply` (J5) composed over KG + vec + symbol. Daily reconciler worker (doc 05 §5).

**Features:** G5, G8.

**Engineer-weeks:** 3–4.

**Exit criteria.**

1. `engram.contradicts({"text": <entity_confusion_fixture>})` returns at least one `entity_confusion` issue from MemPalace's `fact_checker._check_entity_confusion` (02 §5) — fixture drops a known near-duplicate into the palace first.
2. `engram.contradicts` when `fact_checker` cannot be imported (simulated via Python monkeypatch) returns `{error: {code: "fact-checker-unavailable"}}` — verifies the degraded-mode envelope from doc 07 §6.
3. `engram.where_does_decision_apply({"decision_entity": "graphql_migration"})` against the fixture returns a non-empty `implementations` list whose first result's `symbol.name_path` matches a seeded fixture expectation.
4. Reconciler dry-run via `engram reconcile --scope all --dry-run` reports discrepancies without mutating. Live run updates `meta.last_reconcile_at`.
5. Fixture test for reconciler: delete a drawer directly from MemPalace's Chroma, then run the reconciler; stale `anchors_symbol_memory` rows are removed.

**Upstream PRs required:** none.

---

## M4 — Fast sync + confidence decay + audit log

**Scope.** Node shim at `shims/claude-context-sync/` that wraps chokidar on file save and calls `Context.reindexByChange()` through the core JS API (**bypassing the 5-minute MCP tick**). Confidence-decayed anchors (G16). Engram-side audit log (G22).

**Features:** G3 (sub-minute), G16, G22.

**Engineer-weeks:** 2–3.

**Exit criteria.**

1. With the shim running, `engram.health.upstreams.claude_context.last_reindex_age_seconds` drops below 60 seconds within 2 minutes of an editor file save — verified by an end-to-end test that modifies a fixture file and watches the value.
2. Reconciler decreases `anchors_symbol_memory.confidence` on a fixture where a symbol is removed but its drawer remains — verifies decay without deletion.
3. Audit log file at `.engram/logs/audit.jsonl` contains one entry per `engram.*` tool call with deterministic fields (timestamp, tool, args-hash, result-hash).

**Upstream PRs required:**

- **PR-SER-1 (optional):** Add an `on_tool_invoked` callback to `serena.tools.tools_base.Tool.apply_ex` (cited at `serena/src/serena/tools/tools_base.py:307-399`). Additive; gives Engram a direct hook instead of wrapping at the MCP layer. Not blocking — Engram works without it — but cleaner if accepted. **Draft PR spec:**
  - File: `serena/src/serena/tools/tools_base.py`
  - Add class var `_on_tool_invoked_callbacks: list[Callable] = []` to `Tool`.
  - Add classmethod `register_callback(fn)`.
  - Modify `apply_ex` to invoke callbacks with `(tool_name, args, result)` after the tool completes.
  - Likely accepted because: additive, no behavior change when list is empty, matches the existing hook pattern in `serena/src/serena/hooks.py`.

- **PR-CC-1 (optional):** Add a `sync_now(path)` MCP tool to claude-context that triggers `Context.reindexByChange()` out-of-band. File: `claude-context/packages/mcp/src/index.ts` — add tool registration alongside the existing four (`:121-227`). Additive. Removes the need for Engram's Node shim.
  - Likely accepted because: the 5-minute default is already documented as a design trade-off in `claude-context/packages/mcp/src/sync.ts:134-139`; on-demand sync is a commonly-asked feature. If accepted, Engram drops the shim in M4.1.

---

## M5 — UI, federation, enterprise polish

**Scope.** Open-ended; driven by user demand.

**Features:** G7 (graph UI), G13 (query plan explainer UI), G15 (decision-diagram UI), G19 (multi-workspace federation). Possibly a hosted LLM summarization layer (previously cut as G20; reintroduced only if users demand it and the verbatim-retention guarantee is preserved).

**Engineer-weeks:** 8+ (scope-variable).

**Exit criteria.** Defined per feature when prioritized.

**Upstream PRs required:** none anticipated; UI is orthogonal to upstream contracts.

---

## Cross-cutting concerns

### Test fixtures

`tests/fixtures/sample_workspace/` contains:

- ~20 Python files with intentional symbol overlap (testing `find_referencing_symbols`).
- ~10 pre-seeded MemPalace drawers across 3 wings / 6 rooms.
- ~3 KG triples with `valid_to` timestamps to test temporal queries.
- A golden-snapshot of expected Engram tool output for each milestone's exit tests.

### CI pipeline (M0 onward)

- Lint (`ruff check`) + type-check (`mypy src/engram`).
- Unit tests (`pytest tests/unit/`).
- Integration tests (`pytest tests/integration/`) in a container with Milvus + Ollama.
- Smoke test job that runs `engram smoke-test` against a fresh ephemeral workspace.
- Description-lint gate on `engram.*` tools.

### Observability in production

Every milestone ships `engram.health` metrics. `M4` audit log adds structured event tracing. Dashboarding is explicitly M5.

### Risk buffers

Each M estimate above carries a nominal ±20% buffer (not double-counted in totals; use for retros).

---

## Milestone dependency graph

```
M0  ──►  M1  ──►  M2  ──►  M3
                   │
                   └──►  M4  ──►  M5
```

M1 blocks M2 (router reads anchor tables). M2 blocks M3 (features compose router calls). M4 is parallel-compatible with M3 after M2 ships. M5 draws from all prior.

---

## Go / no-go gates

- **Ship M0** when all six M0 exit criteria pass on three canonical fixtures.
- **Start M1** when ≥2 developers are available OR the single developer has ≥4 weeks of uninterrupted time.
- **Ship v1 (end of M3)** when 14 of 16 M0–M3 exit criteria pass. Two soft misses (marked L in priority) are acceptable if documented.
- **Promote M4** when measured path-C freshness complaints exceed a threshold (TBD by ops).

## Assumptions

- Upstream versions pinned at M0 (`serena-agent==1.1.2`, `mempalace==3.3.3`, `@zilliz/claude-context-mcp@0.1.8`) do not regress on the observed surfaces. Minor version bumps during M0–M3 are re-tested against exit criteria.
- Docker + Node are available on every developer's machine; `engram init` enforces this loudly rather than silently falling back.
- Engineer-week estimates assume no prior Engram infrastructure; if a subset ships early as a prototype, subsequent M's compress.

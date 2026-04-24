## 1. M0 — Shell + topology

- [x] 1.1 Scaffold Python package `engram/` (pyproject, src layout, Python 3.11 pin)
- [x] 1.2 Implement `engram init` CLI — config scaffold, SQLite schema bootstrap, prerequisite checks (Python / Node / Docker)
- [x] 1.3 Implement `engram mcp` stdio server registering all four namespaces
- [x] 1.4 Implement pass-through proxy for `code.*` (Serena), `mem.*` (MemPalace), `vec.*` (claude-context) — no write interception yet
- [x] 1.5 Implement `engram.health` tool — per-upstream probe + latency + anchor-store counts
- [x] 1.6 Ship `engram/deploy/compose.yaml` for Milvus + Ollama
- [x] 1.7 Install supervisor unit (launchctl/systemd --user) in `engram init`
- [x] 1.8 Implement `engram smoke-test` — ping upstreams + vec.index fixture + assert health.ok
- [x] 1.9 Implement `engram status` human-readable summary
- [x] 1.10 Write description linter for `engram.*` two-line rule (CI gate)
- [x] 1.11 Commit `tests/fixtures/sample_workspace/` + `tests/fixtures/schema.sql`

## 2. M1 — Link Layer + WAL tailer

- [x] 2.1 Implement 7-table SQLite schema + 3 unique partial indices (`link-layer` spec)
- [x] 2.2 Implement `symbols` / `symbol_history` write path
- [x] 2.3 Implement WAL tailer for `~/.mempalace/wal/write_log.jsonl` with persisted byte-offset cursor
- [x] 2.4 Implement `engram.anchor_memory_to_symbol` tool with idempotent insert
- [x] 2.5 Implement `engram.anchor_memory_to_chunk` tool with `drawer-not-found` validation
- [x] 2.6 Implement write-path interception for `code.rename_symbol` + `code.safe_delete_symbol` (DB tx first, Serena second, commit on success)
- [ ] 2.7 Implement write-path interception for `code.replace_*` / `code.insert_*` / `code.create_text_file` (anchor cache invalidation)
- [x] 2.8 Wire rename → KG triple insert + invalidate in `mem.kg_add` / `mem.kg_invalidate`
- [x] 2.9 Implement `engram.symbol_history` tool
- [x] 2.10 Implement `mem.add` anchor fast-path (optional `anchor_symbol_name_path` + `anchor_relative_path`)
- [x] 2.11 Add `wal_lag_seconds` + `anchor_store` counts to `engram.health`

## 3. M2 — Retrieval Router + RRF fusion

- [x] 3.1 Implement path classifier covering all input shapes (query-only, name_path-only, both)
- [ ] 3.2 Implement Path A (discovery-first) dispatcher
- [ ] 3.3 Implement Path B (precision-first) dispatcher
- [ ] 3.4 Implement Path C (fusion) dispatcher with parallel source dispatch
- [x] 3.5 Implement RRF k=60 fusion with truncation to K=20
- [ ] 3.6 Implement LRU cache (default 1024 entries) keyed on `(tool_name, canonicalized_args)`
- [ ] 3.7 Implement cache invalidation on Link Layer events (rename / delete / move)
- [ ] 3.8 Implement entity extractor (symbol name_paths, file paths, decision entities)
- [x] 3.9 Implement `engram.why` composing symbol + memories + KG facts (Path B full; Path C deferred until dispatcher lands)
- [ ] 3.10 Implement `enclosing_symbol` enrichment for `vec.search` results
- [ ] 3.11 Commit `pytest-benchmark` baselines for path-A/B/C warm P50 budgets

## 4. M3 — Features J4 / J5 + reconciler

- [ ] 4.1 Implement `engram.contradicts` via in-process `fact_checker.check_text` import (preferred path)
- [ ] 4.2 Implement `engram.contradicts` subprocess fallback (`python -m mempalace.fact_checker`)
- [ ] 4.3 Implement `engram.where_does_decision_apply` (KG → vec → symbol composition)
- [ ] 4.4 Implement reconciler job (symbols / chunks / memories / all scopes)
- [ ] 4.5 Wire reconciler to 24-hour schedule + ad-hoc `engram.reconcile` tool + `engram reconcile` CLI
- [ ] 4.6 Add tombstone logic to `symbol_history` for memory / chunk deletions detected by the reconciler

## 5. Cross-cutting — response envelope, errors, versioning

- [ ] 5.1 Implement `{result, meta}` / `{error, meta}` envelope helper used by every `engram.*` and every proxy tool
- [ ] 5.2 Codify stable error-code taxonomy as an enum; reject unknown codes in CI
- [ ] 5.3 Add `meta.path_used`, `meta.cache`, `meta.latency_ms`, `meta.protocol_version` to router responses
- [ ] 5.4 Pin `protocol_version` = v1 in `engram.health` output
- [ ] 5.5 Start-up collision check: fail `engram mcp` if any fully-qualified tool name duplicates

## 6. Testing

- [ ] 6.1 Unit tests: path classifier (≥95% on all 7 rows of the decision table)
- [ ] 6.2 Unit tests: RRF fusion vs. hand-computed fixture
- [ ] 6.3 Unit tests: SQLite idempotency on anchor inserts
- [ ] 6.4 Integration test: full rename flow (Engram tx → Serena → DB commit → KG triple)
- [ ] 6.5 Integration test: WAL tailer lag ≤ 2 s after `mem.add`
- [ ] 6.6 Integration test: reconciler dry-run hash-stability + live-run dangling anchor removal
- [ ] 6.7 Integration test: single upstream crash isolation + supervisor restart
- [ ] 6.8 Golden-file test: `mem.traverse` pass-through byte-identity (except `meta`)
- [ ] 6.9 Smoke-test gate passing on the M0 / M1 / M2 / M3 exit criteria in `10-phased-roadmap.md`

## 7. Docs + release

- [ ] 7.1 Write user-facing README with `engram init` → `smoke-test` quickstart
- [ ] 7.2 Write MCP-client integration notes for Claude Code / Cursor / Claude Desktop
- [ ] 7.3 Publish first PyPI wheel + tag v1.0.0
- [ ] 7.4 File optional upstream PRs (PR-SER-1 hook callback, PR-CC-1 sync_now tool) with draft diffs

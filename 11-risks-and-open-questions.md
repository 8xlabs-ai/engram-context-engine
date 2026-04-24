# 11 — Risks and Open Questions

> Status: **draft**. Every risk and every open question surfaced elsewhere in the bundle, promoted here with ID, statement, evidence, likelihood, impact, mitigation, owner-to-be-named. Open questions are phrased such that a single human answer closes them.

**Severity scale.** L = low. M = medium. H = high. Likelihood × Impact in the leftmost column.

---

## Risks

| ID | L×I | Risk | Evidence | Mitigation | Owner TBD |
|---|---|---|---|---|---|
| R1 | M×H | **Language split** — claude-context is Node, Engram is Python. Cross-language orchestration adds latency and removes some hook options. | Doc 03 §13. Node 20–24 version constraint. | Shape-A (doc 04 §6) — accept MCP-stdio as the uniform transport; M4 Node shim for sub-minute sync only if needed. | Engineer 1 |
| R2 | M×M | **Serena has no external hook surface** — anchor freshness depends on polling or Engram being the tool caller. | Doc 01 §5, §8. `restart_language_server` at `serena/src/serena/tools/symbol_tools.py:21` explicitly exists because of external-edit invisibility. | Doc 05 §4.1 wraps Engram's tool dispatch; doc 05 §5.3 stale-window budget caps correctness loss. | Engineer 2 |
| R3 | L×H | **Rename propagation from external sources invisible** — developer edits in their own IDE go unseen by Engram until reconciliation. | Doc 01 §8 (no filesystem watcher); doc 05 §5.3. | Daily reconciler + optional M4 watcher. | Engineer 2 |
| R4 | L×M | **`fact_checker.py` status could change** — if MemPalace wires it into the write path upstream, Engram's `engram.contradicts` doubles up. | Doc 02 §5 verdict (currently not wired). | Watch MemPalace CHANGELOG; `engram.contradicts` has a short-circuit when MemPalace already surfaces the issue. | Engineer 1 |
| R5 | M×M | **Milvus operational cost** — self-host requires Docker + non-trivial compose. | Doc 03 §9 (no bundled compose). | Ship `engram/deploy/compose.yaml` (doc 09 §6). | Engineer 1 |
| R6 | M×M | **5-minute claude-context tick bounds anchor freshness** — users expecting near-real-time may be surprised. | Doc 03 §6 verdict. | Document the window in `engram init` output; M4 shim for sub-minute. | Engineer 2 |
| R7 | L×M | **WAL can miss entries under rare error paths** — MemPalace logs to stderr on WAL write failure but still commits. | Doc 02 §10 (`mcp_server.py:159-161`). | Daily reconciler diffs Engram's anchor list against live MemPalace. | Engineer 2 |
| R8 | L×L | **Upstream version drift** — a minor bump to Serena / MemPalace / claude-context breaks an assumption. | All three are pre-1.0 versions (`0.1.8`, `1.1.2`, `3.3.3`) with no stability guarantees beyond MCP tool names. | Pin versions in `pyproject.toml` (doc 09 §2); CI smoke tests catch breakages at upgrade time. | Engineer 1 |
| R9 | L×M | **Agent-client tool dropdown overflow** — ~80 tools may overwhelm some clients. | Doc 07 §8 Assumptions. | Namespace-aware filtering in supported clients; description-based deprecation hints for legacy duplicates. | Engineer 1 |
| R10 | L×L | **SQLite busy-timeout contention** under heavy reconcile + router concurrent load. | Doc 05 §1 configures 5 s timeout. | M2 exit criterion benchmarks; raise timeout if contention observed. | Engineer 2 |
| R11 | M×L | **Embedding provider API cost** — if a user picks OpenAI, large-codebase indexing triggers many embedding calls. | Doc 03 §4. | Default to Ollama in `engram init`; OpenAI requires explicit opt-in + confirmation. | Engineer 1 |
| R12 | L×M | **Chroma HNSW segment staleness** — if MemPalace's quarantine doesn't catch a stale segment, searches return wrong drawers. | Doc 02 §12 (`backends/chroma.py:52-130`). | Daily reconciler cross-checks Chroma query results against Engram's anchor list; mismatches trigger an alert. | Engineer 2 |
| R13 | L×M | **Node version compat** — claude-context incompatible with Node ≥ 24 (doc 03 §13 cites README). | Enforced only at README level, not `engines`. | `engram init` hard-refuses Node ≥ 24 with a clear error. | Engineer 1 |
| R14 | L×H | **Transaction partial-commit on rename** — Engram DB tx commits, Serena `rename_symbol` then fails. | Doc 05 §4.1. | Roll back Engram tx on Serena failure; expose `consistency-state-hint` (doc 07 §6). | Engineer 2 |
| R15 | L×L | **Engram-introduced collisions** on the `engram.*` namespace as it grows. | Doc 07 §1. | CI linter that asserts namespace uniqueness across all registered tools. | Engineer 1 |
| R16 | M×L | **MCP stdio round-trip cost > assumption** — if empirically 10×+ our ~1 ms assumption, path C budgets blow up. | Doc 06 §7, §10 Assumptions. | M2 benchmarking; cache TTLs recalibrated if needed. | Engineer 2 |
| R17 | L×M | **Description-linting burden** — every new tool needs the two-line pattern; easy to slip. | Doc 07 §5. | CI gate. | Engineer 1 |
| R18 | L×H | **MemPalace WAL rotation** — if the WAL file gets rotated/truncated by a future MemPalace version, Engram's cursor breaks. | Doc 05 §4.2 assumption; rotation policy not observed in current MemPalace. | Widen cursor to `(file_name, offset)`; test against simulated rotation. | Engineer 2 |

---

## Open questions

Each is yes/no or single-value.

### Q-04-SHAPE

> Should the plan stay on Shape-A (MCP-client orchestrator) or switch to Shape-B / Shape-C?

- **Default:** Shape-A (doc 04 §6).
- **Answer needed:** yes to keep / no + which shape.
- **Resolution:** sets the rest of the bundle's integration contract. User deferred to the plan; doc 04 §6 recommends Shape-A.

### Q-05-WAL-ROTATION

> Does MemPalace rotate / truncate `~/.mempalace/wal/write_log.jsonl` on any schedule, or is it append-only-forever?

- **Default assumption:** append-only, never rotated (doc 02 §10 observed behavior).
- **Answer needed:** ask upstream maintainers via issue on MemPalace repo.
- **Resolution:** if rotated, widen the WAL cursor to `(file_name, offset)`. Affects doc 05 §4.2 implementation, not design.

### Q-08-G17

> If MemPalace ever wires `fact_checker` into its own write path, do we reactivate G17 (auto-populate KG from drawer writes) in Engram?

- **Default:** no — G17 was cut because it contradicts MemPalace's design (02 §4).
- **Answer needed:** yes / no, or "revisit when upstream changes."
- **Resolution:** doc 08 row for G17 becomes "reopen condition met" with a fresh estimate.

### Q-09-MCP-CLIENT-SUPPORT

> Do the three targeted MCP clients (Claude Code, Cursor, Claude Desktop) each accept an 80-tool registration without UI truncation?

- **Default assumption:** yes (doc 07 §8 Assumptions).
- **Answer needed:** empirical yes/no from a live test at M0.
- **Resolution:** if no, add a `--profile minimal|full` switch to Engram's MCP surface (publish only `engram.*` in `minimal`).

### Q-10-PR-SER-1

> Will Serena upstream accept a `Tool.apply_ex` `on_tool_invoked` callback (PR-SER-1 in doc 10 M4)?

- **Default:** unknown.
- **Answer needed:** open a draft PR and see.
- **Resolution:** if accepted, Engram removes its MCP-layer wrapper logic. If rejected, stay with the wrapper.

### Q-10-PR-CC-1

> Will claude-context upstream accept a `sync_now(path)` MCP tool (PR-CC-1)?

- **Default:** unknown.
- **Answer needed:** open a draft PR.
- **Resolution:** if accepted, Engram drops its Node shim in M4.1.

### Q-11-RECONCILER-SCALE

> For monorepos ≥ 1M LOC / ≥ 500k symbols, is daily full reconciliation tolerable, or do we need an incremental reconciler in v1?

- **Default:** tolerable for v1 (doc 05 §14 Assumptions).
- **Answer needed:** yes / no from at least one large-repo pilot user.
- **Resolution:** if no, design incremental reconciliation in M3 or M4.

### Q-12-CONFIG-FORMAT

> Should `.engram/config.yaml` be committed to the repo (shared with team) or `.gitignore`d (per-dev)?

- **Default:** committed — doc 09 §3 notes "safe to commit."
- **Answer needed:** yes / no.
- **Resolution:** if per-dev, `engram init` drops an entry into `.gitignore` automatically.

### Q-13-EMBEDDING-DEFAULT

> Should `engram init` default to Ollama (local, free) or prompt the user to pick?

- **Default:** Ollama (doc 09 §6, §10 R11).
- **Answer needed:** yes / no.
- **Resolution:** if prompt, add an interactive step to `engram init`.

### Q-14-SUBPROCESS-SUPERVISOR

> Does Engram manage the three upstream subprocesses itself (supervise + restart on crash), or does it assume they're started externally (systemd / launchd)?

- **Default:** Engram manages them via `src/engram/upstream/supervisor.py` (doc 09 §1).
- **Answer needed:** yes / no.
- **Resolution:** if externally managed, drop the supervisor module; `engram init` becomes a pure "verify reachable" check.

### Q-15-LICENSING-POSTURE

> Engram's own license — MIT (matches all three upstreams) or Apache 2.0 (adds patent grant)?

- **Default:** MIT (doc 09 §1, §2).
- **Answer needed:** one of.
- **Resolution:** LICENSE file stamp.

### Q-16-TELEMETRY

> Does Engram collect anonymous usage telemetry?

- **Default:** no, per the spirit of MemPalace's "Privacy by architecture" (02 CLAUDE.md).
- **Answer needed:** yes / no.
- **Resolution:** if yes, design an opt-in flag; default off.

### Q-17-HOSTED-LLM-SUMMARIZATION

> Reopen G20 (hosted LLM summarization) for M5, given that the verbatim retention guarantee can be preserved (the summary is a derived value, not a replacement for the drawer)?

- **Default:** no (doc 08 G20 cut).
- **Answer needed:** yes / no.
- **Resolution:** doc 08 row for G20 reopens if yes.

---

## Investigation blockers (came up empty; need human resolution)

### B1 — MemPalace WAL rotation policy

- **What I searched:** `rg "rotate|truncate|rollover|logrotate|os.rename" mempalace/mempalace/mcp_server.py` — no matches for WAL rotation logic.
- **Search also:** `rg "write_log" mempalace/mempalace/` — only the WAL-writer references.
- **Conclusion:** probably append-only-forever, but not definitively confirmed. See Q-05-WAL-ROTATION.

### B2 — Exact claude-context `engines` constraint

- **What I searched:** `packages/package.json` + `package.json`.
- **Conclusion:** README says `< 24.0.0` but the `engines` field in `package.json` specifies only `>=20.0.0`. Engram's `engram init` enforces the upper bound explicitly; this is a documentation gap in claude-context, not a blocker.

### B3 — `precompact_hook.sh` internals

- **What I searched:** `mempalace/hooks/mempal_precompact_hook.sh` — 7.4 KB shell script, not deeply traced beyond file size.
- **Conclusion:** not load-bearing for Engram design; doc 02 §9 covers the hook direction (one-way Claude Code → MemPalace).

---

## Prioritized "must resolve before M2" list

In rough order of importance:

1. **Q-04-SHAPE** — default Shape-A; user can overrule before M0 ships. (Minor impact if answered later — M0 work is mostly shape-agnostic.)
2. **Q-10-PR-SER-1 / Q-10-PR-CC-1** — draft PRs filed as soon as M1 is underway, so the reviews land in time for M4.
3. **Q-09-MCP-CLIENT-SUPPORT** — empirical test during M0 exit criteria.
4. **Q-05-WAL-ROTATION** — file a question upstream with MemPalace; default assumption works for v1 but pin down before a year of operation.

Everything else can sit in the backlog and be answered as it becomes blocking.

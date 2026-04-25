# Engram

A unified coding-agent substrate that composes three open-source MCP servers behind one endpoint:

- **Serena** — LSP-backed symbol search (`code.*`, ~26 tools).
- **MemPalace** — verbatim memory + temporal knowledge graph (`mem.*`, ~29 tools).
- **claude-context** — vector code search backed by Milvus (`vec.*`, 4 tools).

Engram adds a **Link Layer** (SQLite anchor store keeping symbols ↔ memories ↔ chunks correct across renames and moves) and a **Retrieval Router** (path A discovery / path B precision / path C RRF k=60 fusion) — exposed as 8 composed `engram.*` tools.

```
agent client (Claude Code / Cursor / Claude Desktop)
        │ stdio MCP
        ▼
   ┌──────────────────────────────────────────┐
   │  engram-mcp  (Python)                    │
   │  • registry (no-collision check)         │
   │  • router (A / B / C + RRF k=60)         │
   │  • write-path interceptors               │
   │  • LRU cache                             │
   │  • Link Layer ─► .engram/anchors.sqlite  │
   │  • WAL tailer                            │
   │  • reconciler                            │
   └─────┬────────┬─────────────┬─────────────┘
   stdio │  stdio │       stdio │
         ▼        ▼             ▼
      Serena  MemPalace   @zilliz/claude-context-mcp
                           │
                           └─► Milvus + Ollama  (compose stack)
```

## Status

v1 foundation complete + post-archive hardening (LICENSE, Serena warm-up, mem.search keyword normalization, scheduler, hook bus, router benchmarks). **130+ unit tests green + 3 benchmarks under spec budgets** (see [Recently fixed](#recently-fixed) and [Known gaps / TODO](#known-gaps--todo)). Source of truth: `openspec/specs/` for behavior, `00-12-*.md` for rationale.

---

## Quick install (`setup.sh`)

One command does prereq checks, venv, pip, npm, compose, ollama model pull, `engram init`, config patch, and `engram smoke-test`:

```bash
git clone <repo> && cd engram
./setup.sh --workspace /path/to/your/repo
```

It is idempotent — safe to re-run. Useful flags:

| Flag | Effect |
|---|---|
| `--workspace DIR` | Where `.engram/` lives (default: `$PWD`). |
| `--skip-compose` | Don't touch Docker (assume Milvus + Ollama already running, or skip them). |
| `--skip-npm` | Don't install `@zilliz/claude-context-mcp` globally; let `npx` pull lazily. |
| `--force-init` | Overwrite an existing `.engram/config.yaml`. |
| `--no-smoke` | Skip the final `engram smoke-test` (faster on cold runs). |
| `--help` | Print usage banner. |

After it finishes, register `engram-mcp` with your agent client — see §7. If you'd rather drive each step by hand, sections §1–§6 below cover the same ground.

---

## 1. Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | ≥ 3.11, < 3.15 (3.13 or 3.14 OK) | `pyproject.toml` pin; Serena needs ≥3.11 |
| Node | ≥ 20, < 24 | claude-context-mcp constraint |
| Docker + `docker compose` | any recent | Milvus + Ollama stack |
| Platform | macOS or Linux | OS-level supervisor units only for these |

`engram init` checks all three. Pass `--skip-prereq-check` to bypass in CI.

---

## 2. Install

```bash
git clone <repo>
cd engram

python3.13 -m venv .venv
source .venv/bin/activate

pip install -e '.[dev]'
# pulls serena-agent==1.1.2, mempalace==3.3.3, mcp, pydantic, click,
# watchdog, pyyaml, aiosqlite, anyio + dev (pytest, ruff, mypy)

# claude-context: install globally OR let `npx` pull lazily on first run
npm install -g @zilliz/claude-context-mcp@0.1.8
```

> **Note on Python 3.14.** The transitive `anthropic` SDK warns *"Core Pydantic V1 functionality isn't compatible with Python 3.14 or greater."* Cosmetic only — Engram itself uses Pydantic v2.

---

## 3. Boot the compose stack

```bash
docker compose -f deploy/compose.yaml up -d
docker compose -f deploy/compose.yaml ps   # wait for "healthy" on milvus + ollama
docker exec deploy-ollama-1 ollama pull nomic-embed-text   # ~274 MB
```

Services exposed:

| Service | Port | Image |
|---|---|---|
| `etcd` | (internal) | `quay.io/coreos/etcd:v3.5.5` |
| `minio` | (internal) | `minio/minio:RELEASE.2023-03-20T20-16-18Z` |
| `milvus-standalone` | `19530` | `milvusdb/milvus:v2.4.9` |
| `ollama` | `11434` | `ollama/ollama:0.3.12` |

---

## 4. Initialize a workspace

```bash
cd /path/to/your/repo
git init                              # Serena likes a git project
engram init --embedding-provider Ollama
# → writes .engram/config.yaml + .engram/anchors.sqlite
# → seeds meta keys (mempalace_wal_cursor, last_reconcile_at, claude_context_index_generation)
```

---

## 5. Patch the config (one-time, important)

`.engram/config.yaml` defaults assume `serena` and `mempalace-mcp` are on `PATH` and that Serena has no project to attach to. Two edits make it work when launched from an MCP client:

```yaml
upstreams:
  serena:
    command:
      - /abs/path/to/.venv/bin/serena       # was: serena
      - start-mcp-server
      - --project                            # NEW
      - /abs/path/to/your/repo               # NEW
  mempalace:
    command:
      - /abs/path/to/.venv/bin/mempalace-mcp  # was: mempalace-mcp
```

claude-context env vars (`EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `MILVUS_ADDRESS`, `OLLAMA_MODEL`, `OLLAMA_HOST`) are derived from the config and propagated to the subprocess automatically — no edits needed.

---

## 6. Verify health

```bash
engram smoke-test --workspace /path/to/your/repo
# exits 0 when all 3 upstreams probe ok

engram status --workspace /path/to/your/repo
# engram 0.1.0
#   workspace: /path/to/your/repo
#   anchor db: /path/to/your/repo/.engram/anchors.sqlite
#   status:    ok
#   upstreams:
#     serena          ok (50.0 ms)
#     mempalace       ok (5800.0 ms)
#     claude_context  ok (4.8 ms)
#   anchor store:
#     symbols                  0
#     anchors_symbol_memory    0
#     anchors_symbol_chunk     0
```

First-call latencies: Serena ~50 ms, MemPalace ~5–6 s (Chroma + embedding model load), claude-context <50 ms.

---

## 7. Register with an MCP client

Engram is registered as a single MCP server; the three upstreams stay invisible to your agent.

### Claude Code

```bash
claude mcp add engram \
  --scope user \
  --env ENGRAM_WORKSPACE=/abs/path/to/your/repo \
  -- /abs/path/to/.venv/bin/engram-mcp
```

### Cursor — `~/.cursor/mcp.json`

```json
{
  "mcpServers": {
    "engram": {
      "command": "/abs/path/to/.venv/bin/engram-mcp",
      "args": [],
      "env": { "ENGRAM_WORKSPACE": "/abs/path/to/your/repo" }
    }
  }
}
```

### Claude Desktop — `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "engram": {
      "command": "/abs/path/to/.venv/bin/engram-mcp",
      "args": [],
      "env": { "ENGRAM_WORKSPACE": "/abs/path/to/your/repo" }
    }
  }
}
```

`engram-mcp` reads `ENGRAM_WORKSPACE` on startup and refuses to start without it (or a `.engram/config.yaml` in CWD).

---

## 8. Tool surface

When all three upstreams are up, `tools/list` returns ~67 tools across four namespaces:

| Namespace | Backed by | Count | Notes |
|---|---|---|---|
| `code.*` | Serena | ~26 | LSP symbols, file ops; rename/safe_delete intercepted to update Link store + KG |
| `mem.*` | MemPalace | ~29 | CRUD aliased to `mem.add` / `get` / `list` / `update` / `delete`; `mem.add` accepts optional `anchor_symbol_name_path` + `anchor_relative_path` for one-shot anchoring |
| `vec.*` | claude-context | 4 | `vec.index` / `search` / `clear` / `status`; results from `vec.search` carry an `enclosing_symbol` field resolved from the Link store or on-demand from Serena |
| `engram.*` | Engram | 8 | Composed tools — see catalog below |

---

## 9. `engram.*` tool catalog

All responses follow `{result, meta}` (success) or `{error: {code, message, details?}, meta}` (failure). `meta.protocol_version="v1"` and `meta.latency_ms` are always present. Stable error codes: `symbol-not-found`, `drawer-not-found`, `upstream-unavailable`, `timeout`, `invalid-input`, `fact-checker-unavailable`, `all-sources-unavailable`, `consistency-state-hint`.

### `engram.health`

> Report Engram and upstream liveness plus anchor-store counts.
> Use when you need a one-shot status probe before making a compound call.

**Inputs:** none.

**Output:**

```json
{
  "result": {
    "status": "ok",
    "engram_version": "0.1.0",
    "upstreams": {
      "serena":         {"ok": true, "latency_ms": 14.4,  "probe": "get_current_config"},
      "mempalace":      {"ok": true, "latency_ms": 5713,  "probe": "mempalace_status",
                         "wal_lag_seconds": 0.0},
      "claude_context": {"ok": true, "latency_ms": 4.8,   "probe": "get_indexing_status"}
    },
    "anchor_store": {"symbols": 0, "anchors_symbol_memory": 0, "anchors_symbol_chunk": 0}
  },
  "meta": {"protocol_version": "v1", "latency_ms": 6010.3}
}
```

### `engram.anchor_memory_to_symbol`

> Anchor a MemPalace drawer to a code symbol so future queries tie them together.
> Prefer this over writing anchor SQL directly; duplicate calls are idempotent.

**Inputs:** `{drawer_id, name_path, relative_path, confidence?}` (default `confidence=1.0`).

**Output:** `{anchor_id, symbol_id}` plus `meta.symbol_resolved_via_upstream: bool`.

**Errors:** `drawer-not-found`, `invalid-input`. Repeat calls return the existing `anchor_id`.

### `engram.anchor_memory_to_chunk`

> Anchor a MemPalace drawer to a specific code range (file + line span).
> Use when the memory is about a range rather than a whole symbol (e.g., review comments).

**Inputs:** `{drawer_id, relative_path, start_line, end_line, language?}` (default `language="unknown"`).

**Output:** `{anchor_id}`.

**Errors:** `drawer-not-found`, `invalid-input`.

### `engram.symbol_history`

> Return a symbol's identity history (creations, renames, moves, tombstones).
> Use when debugging anchor staleness or answering 'what used to be here?'.

**Inputs:** `{name_path, relative_path?, include_memories?}` (`include_memories=true` joins anchored drawers).

**Output:** `{symbol_id, name_path, relative_path, history: [{old_name_path, new_name_path, source, at_time, ...}], memories?: [...]}`.

**Errors:** `symbol-not-found` if no live row matches `(name_path, relative_path)`.

### `engram.why`

> Explain why a symbol exists: resolve it, list anchored / relevant memories, and KG facts.
> Prefer this over code.find_symbol when the question is *why*, not *where*.

**Inputs:** `{name_path?, relative_path?, free_query?}` — at least one of `name_path` / `free_query` required.

**Output:** `{symbol, memories, facts}`. `meta.path_used ∈ {A, B, C}`.

- `name_path` only → Path B (precision).
- `free_query` only → Path A (discovery).
- both → Path C (fusion).

### `engram.where_does_decision_apply`

> Find every place a KG-recorded decision is implemented in the code.
> Use when you have a decision entity and need to see what code honors it.

**Inputs:** `{decision_entity, limit?}` (default `limit=10`).

**Output:** `{entity, facts, implementations: [{chunk, symbol}]}` — KG → vec search per related term → enclosing symbol resolution.

**Errors:** `invalid-input`.

### `engram.contradicts`

> Run MemPalace's fact_checker against a candidate text and surface contradictions.
> Use when you're about to write a memory and want to catch conflicts before it lands.

**Inputs:** `{text, wing?}`.

**Output:** `{issues: [...]}` (shape from MemPalace's `fact_checker.check_text`).

**Errors:** `invalid-input`, `fact-checker-unavailable` (when neither in-process import nor `python -m mempalace.fact_checker` subprocess can be loaded).

### `engram.reconcile`

> Sweep the anchor store to repair stale rows (dead drawers, tombstoned symbols).
> Use when engram.health reports a large anchor_store age or after a manual cleanup.

**Inputs:** `{scope?, dry_run?}`. `scope ∈ {symbols, chunks, memories, all}` (default `all`).

**Output:** `{scope, dry_run, changed: {symbols, anchors, tombstones}, scanned: {memories, symbols, chunks}, warnings}`.

`dry_run=true` wraps `BEGIN/ROLLBACK` so the SHA-256 of the SQLite file is byte-identical before and after.

---

## 10. Daily commands

```bash
engram mcp                                          # stdio server (agent client launches this)
engram status [--json] [--skip-upstreams]           # health snapshot
engram smoke-test [--workspace DIR] [--skip-upstreams]
engram reconcile --scope all [--dry-run] [--skip-upstreams]
engram supervisor show --platform darwin|linux      # print bundled OS unit template
engram init --workspace DIR [--force]               # bootstrap a workspace
```

`--skip-upstreams` makes the command run against the registry alone — useful in CI or when the compose stack is down.

---

## 11. Optional: persistent OS supervisor unit

Engram's in-process `Supervisor` (in `src/engram/upstream/supervisor.py`) handles per-call subprocess lifecycle. The OS unit only matters if you want upstreams to outlive a single `engram mcp` invocation.

**macOS** (`launchd`):

```bash
engram supervisor show --platform darwin > ~/Library/LaunchAgents/ai.engram.plist
# edit ENGRAM_WORKSPACE inside the file, then:
launchctl load ~/Library/LaunchAgents/ai.engram.plist
```

**Linux** (`systemd --user`):

```bash
mkdir -p ~/.config/systemd/user
engram supervisor show --platform linux > ~/.config/systemd/user/engram.service
# edit ENGRAM_WORKSPACE, then:
systemctl --user daemon-reload
systemctl --user enable --now engram.service
```

---

## 12. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `OPENAI_API_KEY is required for OpenAI embedding provider` | env not propagated to claude-context | pull `cca5674` or later; verify `embedding_provider: Ollama` in config |
| `Tool mem.add not listed by server` | pre-alias build | pull `0b64ffc` or later |
| `Tool vec.status not listed by server` | pre-alias build | pull `11784c8` or later |
| `engram.health` `claude_context.reason="probe returned error"` | probe missing `path` arg | pull `17bc92b` or later |
| `find_symbol` returns null on first call | Serena LSP not warm yet | wait a few seconds, or call `code.activate_project` first (open follow-up) |
| `mem.search` returns 0 hits despite drawers present | `query` arg shape may need tuning | open follow-up — pass through with explicit `top_k` / wing filter |
| `engram-mcp` refuses to start | no `ENGRAM_WORKSPACE` and no `.engram/config.yaml` in CWD | set `ENGRAM_WORKSPACE` in the MCP client config |
| `wal_lag_seconds > 60` in health | WAL tailer not reading | check `~/.mempalace/wal/write_log.jsonl` exists and is appended to |

---

## Recently fixed

| Commit | Fix |
|---|---|
| `cca5674` | Propagate `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `MILVUS_ADDRESS`, `OLLAMA_MODEL`, `OLLAMA_HOST` to the claude-context subprocess. Caught by integration: claude-context defaulted to OpenAI provider, demanded `OPENAI_API_KEY`, crashed at startup. |
| `17bc92b` | claude-context probe now passes `{"path": workspace_root}` to `get_indexing_status`. `engram.health` was reporting `degraded` despite working tools. Same commit also archived `init-engram` change → 34 requirements promoted to `openspec/specs/`. |
| `0b64ffc` | `mem.*` CRUD aliases — `add` / `get` / `list` / `update` / `delete` collapse the `_drawer` / `_drawers` suffix per doc 07 §4. Previously registered as `mem.add_drawer` etc. |
| `11784c8` | `vec.*` aliases — `index` / `search` / `clear` / `status` map to claude-context's verbose names per doc 07 §4. Previously registered as `vec.index_codebase` etc. |
| `031f52b` | Supervisor warms Serena (`activate_project` + `check_onboarding_performed` + optional `onboarding`) after connect. Resolves the "find_symbol returns null on first call against a fresh `--project`" gotcha. |
| `6b6e9f3` | `mem.search` keyword normalization: `Pipeline/process_batch` → `Pipeline process_batch`, max 250 chars, explicit `limit=10`. MemPalace's schema requires keyword-only queries. |
| (HEAD-3) | `ReconcilerScheduler` runs `reconcile(scope=all)` every `reconcile_interval_hours` (default 24, clamped to ≥60s). Records `meta.last_reconcile_at`. Closes original task 4.5. |
| (HEAD-2) | In-process hook bus (`src/engram/events.py`); LRU cache subscribes and evicts on `symbol.renamed` / `symbol.tombstoned` / `file.replaced`. Closes original task 3.7. |

All four MCP-naming/env bugs caught only by real-upstream integration; pure unit tests would not have surfaced them.

---

## Known gaps / TODO

| Item | Status | Workaround / note |
|---|---|---|
| **2.7** — write-path cache invalidation on `code.replace_*` / `insert_*` / `create_text_file` | open | Hook bus now exists; just need to wire `EVENT_FILE_REPLACED` emit on these proxy paths. |
| **7.3** — PyPI `0.1.0` release | release-ready | Workflow `engram-release.yml` + `CHANGELOG.md` shipped; awaiting fresh-machine setup.sh validation + repo secret config before tag. |
| **7.4** — optional upstream PRs (PR-SER-1 `on_tool_invoked`, PR-CC-1 `sync_now`) | deferred | Both additive; current code works without them. |
| **Q-1.7-WATCHDOG** (design.md) | deferred | In-process Supervisor reconnect collides with anyio task-group scopes. OS unit templates ship instead — see §11. |
| **`vec.search` end-to-end with real Ollama** | partial | Pipeline works (`vec.index` + `vec.status` + `vec.search` all execute). First index against real Ollama is multi-minute; no worked example shipped to avoid misleading expectations. |

---

## Layout

```
engram/
├── pyproject.toml
├── README.md
├── CHANGELOG.md
├── LICENSE
├── setup.sh                  (one-shot installer; see Quick install)
├── src/engram/
│   ├── cli.py, config.py, server.py
│   ├── link/{schema.sql, store.py}
│   ├── tools/{registry.py, envelope.py, engram_ns.py, proxy.py,
│   │           write_hooks.py, mem_add_anchor.py, vec_enrich.py,
│   │           contradicts.py, lint.py}
│   ├── upstream/{client.py, supervisor.py}
│   ├── workers/{wal_tailer.py, reconciler.py}
│   ├── router/{classifier.py, fusion.py, dispatcher.py, cache.py, entities.py}
│   └── util/{paths.py, logging.py}
├── deploy/
│   ├── compose.yaml
│   └── units/{ai.engram.plist, engram.service, README.md}
├── tests/
│   ├── unit/                 (16 test files, 113 tests)
│   └── fixtures/{fake_upstream.py, fake_serena.py, fake_mempalace.py,
│                  fake_cc.py, sample_workspace/}
├── openspec/
│   ├── project.md
│   ├── specs/{engram-cli, engram-tools, link-layer, mcp-proxy,
│   │           retrieval-router}
│   └── changes/archive/2026-04-25-init-engram/
└── 00–12-*.md              (planning bundle, ~28k words, source of rationale)
```

---

## Running the test suite

```bash
cd engram
PYTHONPATH=src .venv/bin/pytest tests/unit/         # 130+ unit tests; runs in <10s
PYTHONPATH=src .venv/bin/pytest tests/integration/benchmarks/ \
    --benchmark-only --benchmark-columns=median,mean   # router-overhead P50 gates
```

Unit tests use inline fake MCP servers (`tests/fixtures/fake_*.py`) so the full unit suite runs without installing Serena / MemPalace / claude-context wheels. The benchmark suite measures router-internal overhead against deterministic fake sources; per-spec budgets are Path A ≤150 ms / B ≤100 ms / C ≤300 ms warm P50 (typical observed: ~120 / 120 / 200 μs).

### CI

GitHub Actions workflow at repo-root `.github/workflows/engram-ci.yml` runs on every push and PR that touches `engram/**`:

1. `pip install -e '.[dev]'` in a Python 3.13 venv.
2. `ruff check src tests`.
3. `mypy src/engram` (non-blocking until strict-typed across all modules).
4. `pytest tests/unit/ -q`.
5. `pytest tests/integration/benchmarks/ --benchmark-only` (gates Path A/B/C medians against spec budgets — fails if a router regression pushes any path over).
6. `engram.*` two-line description lint.

### Release

`.github/workflows/engram-release.yml` is a `workflow_dispatch` job that builds wheel + sdist, validates metadata with `twine check`, and (gated on the `publish` input) ships to PyPI. With `publish=false` it dry-runs to TestPyPI. Requires repo secret `PYPI_API_TOKEN` (or OIDC trusted publishing). See `CHANGELOG.md` for the v0.1.0 release checklist.

---

## License

MIT.

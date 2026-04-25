# Changelog

All notable changes to Engram. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the package follows [SemVer](https://semver.org/) once published to PyPI.

## [Unreleased]

Pre-release work in `main`. Will be tagged once a fresh-machine integration run passes against pinned upstream versions.

### Added

- **Setup automation:** `setup.sh` one-shot installer (idempotent) covering prereq checks, venv, pip, npm, compose, ollama model pull, `engram init`, config patch, smoke-test.
- **LICENSE:** explicit MIT license text.
- **Hook bus:** in-process pub/sub at `src/engram/events.py` with stable event types (`symbol.renamed`, `symbol.tombstoned`, `file.replaced`, `memory.written`, `memory.deleted`).
- **LRU cache event subscription:** `LRUCache.subscribe_to(bus)` evicts entries on Link Layer events.
- **File-edit cache invalidation:** `make_file_edit_interceptor` wraps Serena's eight file-edit tools (`replace_symbol_body`, `insert_after_symbol`, `insert_before_symbol`, `replace_content`, `insert_at_line`, `delete_lines`, `replace_lines`, `create_text_file`) and emits `EVENT_FILE_REPLACED` on success. Closes original task 2.7.
- **Reconciler scheduler:** `ReconcilerScheduler` runs `reconcile(scope=all)` every `reconcile_interval_hours` (default 24, clamped to ≥60s); records `meta.last_reconcile_at`.
- **Serena warm-up:** `Supervisor` calls `activate_project` + `check_onboarding_performed` (and `onboarding` if absent) post-connect.
- **Router benchmarks:** `tests/integration/benchmarks/test_router_paths.py` gates Path A/B/C medians against spec budgets (150 / 100 / 300 ms).
- **CI workflow:** `.github/workflows/engram-ci.yml` runs ruff, mypy, unit tests, benchmarks, and `engram.*` description lint on push/PR.
- **Changelog:** this file.

### Changed

- `mcp` dependency loosened from `==1.27.0` to `>=1.26,<2` to coexist with `serena-agent==1.1.2`'s transitive pin.
- `mem.*` proxy now uses CRUD aliases (`add` / `get` / `list` / `update` / `delete`) per spec §4.
- `vec.*` proxy uses verb aliases (`index` / `search` / `clear` / `status`).
- `mem.search` query is normalized to keyword form (`/` and `.` → spaces, ≤250 chars) and now passes `limit=10`.
- `engram.health` claude-context probe sends `{"path": workspace_root}`; previously omitted, causing `degraded` status despite working tools.
- `claude_context` upstream subprocess now receives `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` / `MILVUS_ADDRESS` / `OLLAMA_MODEL` / `OLLAMA_HOST` env vars from config.
- ruff: `line-length=110`; ignores `E741` and `UP036`.

### Fixed

- `engram-mcp` boots cleanly with all three upstreams. Real-upstream integration validated end-to-end:
  - `cca5674` claude-context env propagation.
  - `17bc92b` claude-context probe arg.
  - `0b64ffc` `mem.*` CRUD aliases.
  - `11784c8` `vec.*` aliases.
  - `031f52b` Serena onboarding warm-up.

### Tests

- 130 unit tests + 3 router benchmarks; full suite runs in ~10 s without installing real upstream wheels (uses `tests/fixtures/fake_*.py`).

### Known gaps

See README §"Known gaps / TODO". v0.1.0 ships with task 2.7 (file-edit cache invalidation) reclassified as a 1-line wire-up on top of the new hook bus, and tasks 7.3 / 7.4 / Q-1.7-WATCHDOG deferred.

---

## [0.1.0] — pending

First public PyPI release. Tag when:

- A fresh-machine `setup.sh` run on Linux + macOS reaches `engram smoke-test` green.
- All 4 originally-blocking tasks (env, probe-args, mem aliases, vec aliases) verified on real upstreams.
- 130+ unit tests + 3 benchmarks green in CI.

Release process is documented at `.github/workflows/release.yml` (manual `workflow_dispatch` trigger; uses `PYPI_API_TOKEN` repository secret).

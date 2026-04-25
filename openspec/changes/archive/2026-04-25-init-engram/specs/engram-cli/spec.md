## ADDED Requirements

### Requirement: `engram init` bootstraps a workspace

The command SHALL accept `--embedding-provider <Ollama|OpenAI|Voyage|Gemini|Azure>` (default `Ollama`) and SHALL create `.engram/config.yaml` and `.engram/anchors.sqlite` in the current git repository. It SHALL verify that Python ≥3.11, Node ≥20 <24, and Docker are installed on PATH, failing loudly with a fix-me message if any prerequisite is missing. On success it SHALL exit with status 0.

#### Scenario: Fresh init in an empty repo

- **GIVEN** a git repository with no `.engram/` directory and all prerequisites installed
- **WHEN** `engram init --embedding-provider Ollama` is invoked
- **THEN** `.engram/config.yaml` and `.engram/anchors.sqlite` SHALL be created, exit code SHALL equal 0, AND the SQLite file SHALL already contain the documented 7-table schema.

#### Scenario: Missing Node aborts init

- **WHEN** `engram init` is invoked on a system where `node --version` returns ≥24 or is absent
- **THEN** the command SHALL exit with a non-zero status AND stderr SHALL contain a human-readable instruction naming the required Node version range.

### Requirement: `engram smoke-test` verifies end-to-end plumbing

The command SHALL return exit code 0 only after it has successfully pinged all three upstream subprocesses, run `vec.index` on `tests/fixtures/sample_workspace/` and waited for `status="completed"`, called `engram.health`, and asserted `status=="ok"`.

#### Scenario: Happy-path smoke test passes

- **GIVEN** `engram init` has completed and `docker compose up -d` has started Milvus + Ollama
- **WHEN** `engram smoke-test` is invoked
- **THEN** the command SHALL exit with status 0 within 120 seconds AND stdout SHALL include `"engram.health: ok"`.

#### Scenario: Smoke test fails loudly on degraded health

- **WHEN** one upstream is down and `engram smoke-test` is invoked
- **THEN** the command SHALL exit with a non-zero status AND stderr SHALL name the failing upstream.

### Requirement: `engram mcp` is the foreground MCP server

The command SHALL start a stdio-transport MCP server that exposes the full `code.*` + `mem.*` + `vec.*` + `engram.*` tool set. The number of tools advertised on `tools/list` SHALL be at least 80 and SHALL exactly match the sum of the four namespace counts. Every `engram.*` tool SHALL carry a two-line description where line 1 states intent and line 2 starts with `"Prefer "` or `"Use when "`.

#### Scenario: tools/list returns the full surface

- **WHEN** an MCP client connects to `engram mcp` and calls `tools/list`
- **THEN** the response SHALL include every `engram.*` tool defined in the `engram-tools` spec AND `jq '.tools | length'` SHALL return a value ≥ 80.

#### Scenario: Description linter passes on `engram.*`

- **WHEN** the CI description linter is run against the registered `engram.*` tools
- **THEN** every tool SHALL pass the two-line description check AND the linter SHALL exit 0.

### Requirement: `engram status` summarizes workspace state

The command SHALL print human-readable output that includes current values of `engram.health`'s fields, the path to the anchor DB, the path to the WAL cursor, and the number of active upstream subprocesses.

#### Scenario: Status prints upstream health and file paths

- **WHEN** `engram status` is invoked
- **THEN** stdout SHALL include the strings `"serena:"`, `"mempalace:"`, `"claude_context:"`, AND the full path to `.engram/anchors.sqlite`.

### Requirement: `engram reconcile` is the CLI entry to the reconciler

The command SHALL accept `--scope <symbols|chunks|memories|all>` (default `all`) and `--dry-run` and SHALL produce the same response shape as the `engram.reconcile` MCP tool. It SHALL exit 0 on successful reconciliation regardless of whether rows were changed.

#### Scenario: Dry-run CLI prints counts

- **WHEN** `engram reconcile --scope all --dry-run` is invoked
- **THEN** stdout SHALL include a line matching `changed: {symbols: <int>, anchors: <int>, tombstones: <int>}` AND the SHA-256 of `.engram/anchors.sqlite` SHALL be identical before and after.

### Requirement: `.engram/config.yaml` holds per-workspace configuration

The config file SHALL be a YAML document containing at minimum `embedding_provider`, `upstreams.serena.command`, `upstreams.mempalace.command`, `upstreams.claude_context.command`, `anchor_store_path`, and `wal_cursor_path`. Missing required fields SHALL cause `engram mcp` to exit non-zero with a named error.

#### Scenario: Minimal valid config starts the server

- **GIVEN** a `.engram/config.yaml` containing only the required keys
- **WHEN** `engram mcp` is invoked
- **THEN** the server SHALL start successfully AND `engram.health` SHALL report `status="ok"` within 10 seconds.

#### Scenario: Missing required key aborts start

- **GIVEN** a `.engram/config.yaml` with `embedding_provider` removed
- **WHEN** `engram mcp` is invoked
- **THEN** the process SHALL exit non-zero AND stderr SHALL include the string `"missing required config key: embedding_provider"`.

### Requirement: Process supervision manages three upstream subprocesses

`engram init` SHALL install a user-level supervisor unit (`launchctl` on darwin, `systemd --user` on linux) that starts, monitors, and restarts the three upstream subprocesses independently. Crash of any one upstream SHALL NOT terminate the others. `engram.health` SHALL reflect per-upstream liveness accurately within 5 seconds of a crash.

#### Scenario: Single upstream crash is isolated

- **GIVEN** all four processes are healthy
- **WHEN** the Serena subprocess is killed (SIGKILL) externally
- **THEN** within 5 seconds `engram.health.upstreams.serena.ok` SHALL be `false`, `engram.health.upstreams.mempalace.ok` SHALL remain `true`, `engram.health.upstreams.claude_context.ok` SHALL remain `true`, AND the supervisor SHALL restart Serena within 30 seconds.

### Requirement: Bundled `compose.yaml` brings up Milvus and Ollama

The package SHALL ship `engram/deploy/compose.yaml` that, when run with `docker compose -f engram/deploy/compose.yaml up -d`, SHALL report `milvus-standalone` and `ollama` services as healthy within 60 seconds on a typical developer machine.

#### Scenario: Compose brings services healthy

- **WHEN** `docker compose -f engram/deploy/compose.yaml up -d` is invoked on a clean Docker daemon
- **THEN** within 60 seconds `docker compose ps` SHALL report both services with status `healthy`.

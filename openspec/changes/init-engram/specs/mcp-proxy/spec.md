## ADDED Requirements

### Requirement: `code.*` proxies every Serena tool with a namespace prefix and envelope

The system SHALL expose every tool registered by Serena's `ToolRegistry` under a `code.` namespace prefix. Each `code.*` response SHALL wrap Serena's raw return value in `{result, meta}` where `meta.path_used="B"`, `meta.latency_ms`, and `meta.upstream="serena"` are populated. The `search_for_pattern` tool SHALL additionally be aliased as `code.grep`.

#### Scenario: Every registered Serena tool is proxied

- **WHEN** an MCP client calls `tools/list` against `engram mcp`
- **THEN** for every tool name reported by Serena's registry there SHALL be a corresponding `code.<name>` entry in Engram's list, AND the count of `code.*` tools SHALL equal Serena's registered count (±1 for the `code.grep` alias).

#### Scenario: Pass-through preserves upstream payload

- **WHEN** `code.get_current_config` is invoked
- **THEN** the response's `result` field SHALL be byte-identical to what `serena.get_current_config` returns directly, AND `meta.upstream` SHALL equal `"serena"`.

### Requirement: `code.*` write tools update the Link Layer transactionally

The system SHALL intercept `code.rename_symbol`, `code.safe_delete_symbol`, `code.replace_symbol_body`, `code.insert_before_symbol`, `code.insert_after_symbol`, and `code.create_text_file` to maintain Link Layer consistency. For `rename_symbol` and `safe_delete_symbol`, the system SHALL begin a SQLite transaction before forwarding to Serena and commit only on Serena success. For `replace_*`, `insert_*`, and `create_text_file`, the system SHALL forward first and invalidate the anchor cache for the touched path on success.

#### Scenario: Rename commits only on upstream success

- **WHEN** `code.rename_symbol` is invoked and Serena returns success
- **THEN** the SQLite transaction on `symbols` + `symbol_history` SHALL commit before Engram returns AND the response SHALL be a single `{result, meta}` envelope (no partial state visible to the caller).

#### Scenario: Failed rename rolls back and surfaces consistency hint

- **WHEN** `code.rename_symbol` is invoked and Serena returns an error
- **THEN** the SQLite transaction SHALL roll back AND the response SHALL carry `error.code="consistency-state-hint"` with the affected `symbol_id` in `error.details`.

### Requirement: `mem.*` proxies MemPalace with a shortened prefix

The system SHALL expose every MemPalace tool under the `mem.` namespace with the `mempalace_` prefix dropped (e.g., `mempalace_add_drawer` → `mem.add`, `mempalace_search` → `mem.search`, `mempalace_kg_query` → `mem.kg_query`). Responses SHALL carry `meta.upstream="mempalace"` but SHALL NOT alter MemPalace's payload shape at the proxy layer.

#### Scenario: Shortened tool name routes correctly

- **WHEN** `mem.add` is invoked with a valid drawer payload
- **THEN** MemPalace SHALL receive the call as `mempalace_add_drawer`, Engram SHALL return `{result, meta}`, AND the WAL tailer SHALL observe the write within 2 seconds.

#### Scenario: Golden-file pass-through test matches byte-for-byte except meta

- **WHEN** `mem.traverse` is invoked on a fixture palace and the result is compared with a direct `mempalace_traverse` call on the same palace
- **THEN** the `result` field SHALL be byte-identical and only the `meta` envelope SHALL differ.

### Requirement: `mem.add` optionally creates an anchor in one call

The system SHALL accept optional `anchor_symbol_name_path` and `anchor_relative_path` arguments on `mem.add`. When both are supplied and MemPalace confirms the drawer write, the system SHALL insert exactly one row into `anchors_symbol_memory` before returning. Omitting these arguments SHALL leave `mem.add` as a plain pass-through.

#### Scenario: Anchor fields insert one row after confirmation

- **WHEN** `mem.add(content=..., wing=..., anchor_symbol_name_path="Foo/process", anchor_relative_path="src/foo.py")` is invoked
- **THEN** MemPalace SHALL return a `drawer_id`, exactly one `anchors_symbol_memory` row SHALL be inserted with that `drawer_id` and the resolved `symbol_id`, AND the response's `meta.anchor_id` SHALL contain the new anchor's ID.

#### Scenario: Plain mem.add does not create anchors

- **WHEN** `mem.add(content=..., wing=...)` is invoked with no anchor arguments
- **THEN** no row SHALL be inserted into `anchors_symbol_memory`.

### Requirement: `vec.*` proxies claude-context with enclosing-symbol enrichment

The system SHALL expose exactly four `vec.*` tools — `vec.index`, `vec.search`, `vec.clear`, `vec.status` — that proxy claude-context's `index_codebase`, `search_code`, `clear_index`, and `get_indexing_status`. Each result item returned by `vec.search` SHALL be augmented with an `enclosing_symbol` field resolved from `anchors_symbol_chunk` when available or on-demand from Serena otherwise. `meta.upstream` SHALL equal `"claude-context"`.

#### Scenario: Search results carry enclosing symbol

- **WHEN** `vec.search(query="parse json")` is invoked on a workspace where the top chunk is anchored to symbol `Parser/parse_json`
- **THEN** the first item's `enclosing_symbol.name_path` SHALL equal `"Parser/parse_json"` AND its `enclosing_symbol.relative_path` SHALL match the chunk's file path.

#### Scenario: Unanchored chunk falls back to Serena resolution

- **WHEN** `vec.search` returns a chunk whose `(relative_path, start_line)` has no row in `anchors_symbol_chunk`
- **THEN** the proxy SHALL call Serena `find_symbol` on the chunk's coordinates, populate `enclosing_symbol` from the result, AND lazily insert one row into `anchors_symbol_chunk` for the future hit.

### Requirement: No raw-name collisions across namespaces

The system SHALL ensure that no two tools registered on the Engram MCP surface share the same fully-qualified name across `code.*`, `mem.*`, `vec.*`, and `engram.*`. On start-up, duplicate names SHALL cause `engram mcp` to fail with a non-zero exit code and a diagnostic naming the offending tool.

#### Scenario: Collision at start-up aborts boot

- **WHEN** Engram is started with a misconfiguration that would register both `engram.why` and `code.why`
- **THEN** `engram mcp` SHALL exit with a non-zero status AND stderr SHALL include the string `duplicate tool name: why` naming both namespaces.

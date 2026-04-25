## ADDED Requirements

### Requirement: Response envelope is uniform across every `engram.*` tool

The system SHALL return every `engram.*` tool response as either `{result: ..., meta: {...}}` on success or `{error: {code, message, details?}, meta: {...}}` on failure. `meta.latency_ms` SHALL always be present; `meta.cache` SHALL be `"hit"` or `"miss"` for router-backed tools; `meta.path_used` SHALL be `"A"`, `"B"`, or `"C"` for router-backed tools; `meta.protocol_version` SHALL pin the `engram.*` surface version.

#### Scenario: Success envelope includes required meta fields

- **WHEN** `engram.health` is invoked
- **THEN** the response SHALL be shaped `{result: ..., meta: {latency_ms: <int>, protocol_version: <string>}}` with no `error` key.

#### Scenario: Failure envelope carries a stable error code

- **WHEN** `engram.why(name_path="Bogus/does_not_exist")` is invoked against a workspace where the symbol is not resolvable
- **THEN** the response SHALL carry `error.code="symbol-not-found"`, `error.message` SHALL be populated, AND `meta.latency_ms` SHALL still be present.

### Requirement: Stable error-code taxonomy

The system SHALL use exactly the following error codes and SHALL NOT introduce new codes without a protocol-version bump: `symbol-not-found`, `drawer-not-found`, `upstream-unavailable`, `timeout`, `invalid-input`, `fact-checker-unavailable`, `all-sources-unavailable`, `consistency-state-hint`. `duplicate-anchor` SHALL NOT be returned as an error — it represents a success shape where the existing `anchor_id` is returned.

#### Scenario: Fact-checker unavailable produces a named error

- **WHEN** `engram.contradicts` is invoked and the `fact_checker` module cannot be imported AND the CLI fallback fails
- **THEN** the response SHALL carry `error.code="fact-checker-unavailable"`.

#### Scenario: All upstreams down produces all-sources-unavailable

- **WHEN** a Path-C query is made and all of Serena, MemPalace, and claude-context return errors
- **THEN** the response SHALL carry `error.code="all-sources-unavailable"`.

### Requirement: `engram.anchor_memory_to_symbol` creates or returns an anchor

The tool SHALL take `{drawer_id, name_path, relative_path, confidence?}`, validate that the drawer exists in MemPalace and that the symbol resolves via Serena, then insert into `anchors_symbol_memory` (creating a `symbols` row if absent) and return `{anchor_id}`. Re-calls with identical arguments SHALL be idempotent and return the pre-existing `anchor_id`.

#### Scenario: First call creates a new anchor

- **WHEN** `engram.anchor_memory_to_symbol(drawer_id=D, name_path="Foo/process", relative_path="src/foo.py")` is invoked for the first time
- **THEN** one row SHALL be inserted into `anchors_symbol_memory` AND the response SHALL include `result.anchor_id`.

#### Scenario: Repeat call is idempotent

- **WHEN** the same call is repeated
- **THEN** no new row SHALL be inserted AND the response `result.anchor_id` SHALL equal the first call's.

### Requirement: `engram.anchor_memory_to_chunk` links drawer to code range

The tool SHALL take `{drawer_id, relative_path, start_line, end_line}`, validate the drawer exists, then insert into `anchors_memory_chunk` and return `{anchor_id}`. The call SHALL fail with `drawer-not-found` when the drawer does not exist.

#### Scenario: Valid drawer creates chunk anchor

- **WHEN** `engram.anchor_memory_to_chunk(drawer_id=D, relative_path="src/foo.py", start_line=10, end_line=40)` is invoked with `D` present
- **THEN** one row SHALL be inserted into `anchors_memory_chunk` AND the response SHALL include `result.anchor_id`.

#### Scenario: Missing drawer produces error

- **WHEN** the same call is made with a `drawer_id` that does not exist in MemPalace
- **THEN** the response SHALL carry `error.code="drawer-not-found"`.

### Requirement: `engram.why` composes symbol, memories, and KG facts

The tool SHALL take `{name_path?, relative_path?, free_query?}` with at least one of `name_path` or `free_query` provided, and SHALL return `{symbol, memories, facts}` by calling Serena `find_symbol`, MemPalace `mempalace_search`, and MemPalace `mempalace_kg_query`. When only `name_path` is provided the router SHALL take Path B; when only `free_query` is provided Path C SHALL be taken.

#### Scenario: name_path input returns symbol plus anchored memories

- **WHEN** `engram.why(name_path="Foo/process", relative_path="src/foo.py")` is invoked on a workspace with two anchored drawers
- **THEN** `result.symbol.name_path` SHALL equal `"Foo/process"`, `result.memories` SHALL contain at least two entries each with `drawer_id`, `content`, `similarity`, and `anchor_confidence`, AND `meta.path_used` SHALL equal `"B"`.

#### Scenario: No memories is not an error by default

- **WHEN** `engram.why(name_path=...)` is invoked on a symbol with no anchored memories AND `strict` is not set
- **THEN** the response SHALL succeed with `result.memories=[]` AND SHALL NOT carry an `error` key.

### Requirement: `engram.where_does_decision_apply` finds implementations of a KG decision

The tool SHALL take `{decision_entity, limit?}`, query the MemPalace KG for related facts, dispatch `vec.search` on each related entity, resolve each chunk to an enclosing symbol via Serena, and return `{entity, facts, implementations}`. The router SHALL use Path C with fact-weighted fusion.

#### Scenario: Known decision returns implementation list

- **WHEN** `engram.where_does_decision_apply(decision_entity="graphql_migration")` is invoked against a fixture where the KG names the decision and claude-context has indexed the repo
- **THEN** `result.implementations` SHALL be non-empty AND the first item's `symbol.name_path` SHALL match the fixture's expected value.

### Requirement: `engram.symbol_history` returns the symbol ledger

The tool SHALL take `{name_path, relative_path?, include_memories?}` and read from `symbols` and `symbol_history` (plus optionally `anchors_symbol_memory` → `mem.get` when `include_memories=true`), returning `{symbol_id, history, memories?}`.

#### Scenario: Rename appears in history

- **GIVEN** a symbol that has been renamed once via `code.rename_symbol`
- **WHEN** `engram.symbol_history(name_path=<new_name>, relative_path=<path>)` is invoked
- **THEN** `result.history` SHALL contain at least one entry with `change_kind="rename"` and a `previous_name_path` equal to the old name.

### Requirement: `engram.contradicts` invokes MemPalace fact_checker out-of-band

The tool SHALL take `{text, wing?}`, invoke MemPalace's `fact_checker.check_text()` via in-process import (preferred) or `python -m mempalace.fact_checker` subprocess (fallback), and return `{issues}` matching MemPalace's `fact_checker.check_text` return shape. It SHALL NOT write anything to the Link Layer or to MemPalace as a side-effect.

#### Scenario: Entity confusion is surfaced as an issue

- **GIVEN** a MemPalace fixture with a known near-duplicate entity
- **WHEN** `engram.contradicts(text=<entity_confusion_fixture>)` is invoked
- **THEN** `result.issues` SHALL contain at least one issue whose type equals `"entity_confusion"`.

#### Scenario: Unavailable fact_checker produces named error

- **WHEN** the tool is invoked with both import and subprocess paths simulated as failing
- **THEN** the response SHALL carry `error.code="fact-checker-unavailable"`.

### Requirement: `engram.reconcile` is the ops entry point

The tool SHALL take `{scope?, dry_run?}` with `scope` ∈ `{"symbols", "chunks", "memories", "all"}` (default `"all"`), invoke the reconciler, and return `{changed: {symbols, anchors, tombstones}}`.

#### Scenario: Dry-run reports without mutating

- **WHEN** `engram.reconcile(scope="all", dry_run=true)` is invoked
- **THEN** the response SHALL report counts AND the SHA-256 of `.engram/anchors.sqlite` SHALL be identical before and after the call.

### Requirement: `engram.health` reports per-upstream liveness and store size

The tool SHALL take no inputs and SHALL return `{status, upstreams, anchor_store}` where `status` ∈ `{"ok", "degraded", "down"}`, `upstreams` contains per-upstream `{ok, latency_ms}` plus `mempalace.wal_lag_seconds` and `claude_context.last_reindex_age_seconds`, and `anchor_store` contains integer counts of `symbols`, `anchors_symbol_memory`, and `anchors_symbol_chunk`. The tool SHALL perform exactly one liveness probe per upstream per invocation.

#### Scenario: All healthy upstreams produce status=ok

- **WHEN** `engram.health` is invoked and every upstream responds to its probe within 1 s
- **THEN** `result.status` SHALL equal `"ok"` AND each `upstreams.*.ok` SHALL be `true`.

#### Scenario: One failed upstream produces status=degraded

- **WHEN** `engram.health` is invoked and exactly one upstream probe fails
- **THEN** `result.status` SHALL equal `"degraded"` AND only the failing upstream SHALL report `ok=false`.

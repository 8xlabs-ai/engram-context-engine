## ADDED Requirements

### Requirement: Router selects one of three retrieval paths per query

The system SHALL classify each retrieval request into exactly one of three paths — A (discovery-first), B (precision-first), or C (fusion) — based on the shape of the input, and SHALL report the chosen path in the response via `meta.path_used`.

- Path A is chosen when the caller supplies only a free-text `query` and no `name_path`.
- Path B is chosen when the caller supplies a `name_path` (with or without `relative_path`) and no free-text `query`.
- Path C is chosen when the caller supplies both `name_path` and `query`, or when invoking an `engram.*` composed tool that is explicitly fusion-backed (e.g., `engram.where_does_decision_apply`).

#### Scenario: Free-text query routes to Path A

- **WHEN** the router receives `{query: "hash password with bcrypt"}` with no `name_path`
- **THEN** `meta.path_used` SHALL equal `"A"` AND the first upstream call SHALL be `vec.search`.

#### Scenario: Name_path routes to Path B

- **WHEN** the router receives `{name_path: "Foo/process", relative_path: "src/foo.py"}`
- **THEN** `meta.path_used` SHALL equal `"B"` AND the first upstream call SHALL be Serena `find_symbol`.

#### Scenario: Both inputs route to Path C

- **WHEN** the router receives `{name_path: "Foo/process", query: "batching rationale"}`
- **THEN** `meta.path_used` SHALL equal `"C"` AND the router SHALL dispatch to vec / memory / KG sources in parallel before fusing.

### Requirement: Fusion uses Reciprocal Rank Fusion with k=60

When Path C is taken, the system SHALL combine ranked results from vec, memory, and KG sources using Reciprocal Rank Fusion with constant `k=60`, truncate the fused list to at most 20 items, and report `meta.fusion.k=60` and `meta.fusion.sources_used` in the response.

#### Scenario: RRF order matches hand-computed expected

- **WHEN** the router is given three fixture source lists with known ranks (e.g., `vec=[a,b,c]`, `mem=[b,d,a]`, `kg=[c,a,d]`)
- **THEN** the fused output order SHALL exactly match the RRF-k=60 hand-computed expected ranking committed at `tests/fixtures/rrf_expected.json`.

#### Scenario: Missing source degrades gracefully

- **WHEN** one of the three upstream sources returns an error during a Path-C call (e.g., claude-context is down)
- **THEN** the router SHALL compute RRF over the two surviving source lists, set `meta.fusion.sources_used` to those two, set `meta.warnings` to include the failing source, AND the response SHALL still succeed (not raise `all-sources-unavailable` unless every source failed).

### Requirement: Per-path latency budgets are enforced

The system SHALL enforce warm P50 latency budgets per path measured on the standard fixture workspace: Path A ≤ 150 ms, Path B ≤ 100 ms, Path C ≤ 300 ms. Each response SHALL include `meta.latency_ms`. CI SHALL fail the M2 exit gate if any committed `pytest-benchmark` baseline is regressed by more than 20%.

#### Scenario: Cold-cache latency is reported but not gated

- **WHEN** the first Path-C call after Engram start is made
- **THEN** `meta.cache` SHALL equal `"miss"`, `meta.latency_ms` SHALL be populated, AND the response SHALL succeed even if latency exceeds the warm budget.

### Requirement: LRU cache accelerates repeated queries and invalidates on Link Layer events

The system SHALL cache router responses keyed by `(tool_name, canonicalized_args)` in an LRU cache with a bounded size (default 1024 entries). On symbol rename, delete, or file move events emitted by the Link Layer, cache entries whose key references the affected symbol or path SHALL be evicted before the next read.

#### Scenario: Identical second call hits cache

- **WHEN** an identical `engram.why(name_path=...)` call is made twice consecutively with no intervening Link Layer event
- **THEN** the second response SHALL report `meta.cache="hit"` AND its `meta.latency_ms` SHALL be at least 3× lower than the first call's.

#### Scenario: Rename event evicts affected entries

- **WHEN** `code.rename_symbol` succeeds on symbol `S` and then the same `engram.why(name_path=old_S)` is called again
- **THEN** the response SHALL report `meta.cache="miss"` AND the cache SHALL no longer contain any entry whose canonicalized args reference the old name.

### Requirement: Entity extractor normalizes inputs before dispatch

Before dispatching to upstreams, the router SHALL run an entity extractor over the caller's input to produce normalized `entities` (symbol `name_path`s, file paths, and decision-entity names). This normalized list SHALL be available to all path handlers and SHALL appear in `meta.entities` in the response.

#### Scenario: Free query yields extracted entities in meta

- **WHEN** the router receives `{query: "rename Foo.process to run in src/foo.py"}`
- **THEN** `meta.entities` SHALL contain at least `"Foo/process"` and `"src/foo.py"`.

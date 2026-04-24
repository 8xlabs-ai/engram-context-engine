# 06 — Retrieval Router Design

> Status: **draft**. This document specifies the three canonical query paths, the exact upstream call sequence for each, the fusion algorithm for the three-way join, a decision table mapping query features to paths, and the caching strategy that keeps the router fast.

The Retrieval Router is the second of Engram's two new pieces of substance. Its job is to receive a natural-language or semi-structured query from a user agent and return a single composed answer drawn from the three upstreams, using the Link Layer (doc 05) to stitch across them.

## 1. The three canonical paths

At the top of the router is a **path classifier** that picks one of three execution paths based on query features. The classifier is a small rules table (§4) — not an ML model.

### Path A — Discovery-to-Precision

> *"Show me code that does X."* Natural-language code intent, no specific symbol in mind.

**Call sequence (all MCP, per Shape-A):**

1. `vec.search_code` → claude-context `search_code` (03 §2). Inputs: `{path, query, limit=20, extensionFilter}`. Output: list of chunks `(content, relativePath, startLine, endLine, language, score)`.
2. For each chunk, resolve enclosing symbol via the Link Layer's `anchors_symbol_chunk` table (doc 05 §3.3). Cache miss → call Serena `get_symbols_overview(relative_path)` (01 §2) and populate the anchor.
3. **Optionally enrich with memory** (default on for Engram's `engram.why`-style tools, off for raw `code.search_code`). For each symbol, query Link Layer `anchors_symbol_memory` → for each anchored `drawer_id`, fetch content via `mempalace_get_drawer` (02 §2 entry #22). Attach as `relevant_memories: [...]`.
4. Return composed response: chunks + their resolved symbols + optional memories + provenance trail (which upstream each field came from).

### Path B — Precision-First

> *"Find references to `Foo.process_batch`."* User has a symbol identity.

**Call sequence:**

1. Resolve the symbol: Serena `find_symbol` (01 §2) with the provided `name_path_pattern` and optional `relative_path`. If not found, return a "did you mean" list from the Link Layer's `symbol_history` (doc 05 §2) where fuzzy matches live.
2. `find_referencing_symbols` on the resolved symbol (01 §2). Output: references with surrounding snippets.
3. Optionally join `anchors_symbol_memory` to attach prior discussion drawers.
4. Optionally join `anchors_symbol_chunk` to attach any cached vector chunks for the symbol (use only when `include_chunks=true`; typical precision-first flows don't need it).
5. Return composed response.

### Path C — Fusion (three-way)

> *"What's the decision history around authentication, and where's it implemented?"* Query spans memory + code.

This is the hardest path and the one that justifies the router existing. It runs all three upstreams in parallel, then fuses.

**Call sequence (parallel fan-out, then fuse):**

1. In parallel:
   - `vec.search_code(query)` → claude-context chunk hits.
   - `mem.search(query)` → MemPalace `mempalace_search` (02 §2 entry #18).
   - `mem.kg_query(query_entities_extracted)` → MemPalace `mempalace_kg_query` (02 §2 entry #6) after a cheap entity extraction (see §3).
2. Each result set carries its own score:
   - Chunks: cosine similarity 0.0–1.0 (03 §7).
   - Memories: similarity from MemPalace's hybrid rerank 0.0–1.0 (02 §7).
   - KG facts: no native score; Engram assigns 1.0 to exact entity matches, 0.7 to fuzzy, 0.0 to misses.
3. **Normalize** each score list to ranks (1, 2, 3, …) within its own list.
4. **Fuse via Reciprocal Rank Fusion (RRF)** — see §2.
5. Re-attach the Link Layer to fused results: for each result that is a chunk, resolve its enclosing symbol and anchored memories. For each result that is a memory, resolve anchored symbols.
6. Return a single ranked list where every row has the shape `{kind: "chunk"|"memory"|"fact", content, provenance, links: [...]}`.

## 2. Fusion algorithm — Reciprocal Rank Fusion, k=60

RRF is the default modern rank-fusion algorithm for heterogeneous score sources. Each document's fused score is:

```
rrf_score(d) = Σ_over_sources  1 / (k + rank_source(d))
```

where `rank_source(d)` is `d`'s 1-indexed rank within a source's result list, and `k = 60`.

### Why RRF, specifically

- **Score-scale agnostic.** The three upstreams return scores on incompatible scales (cosine similarity, hybrid BM25+vec, Engram-assigned fact score). RRF only needs ranks.
- **No training required.** The constant `k=60` is the widely-cited default from the original Cormack et al. paper and has held up well against learned alternatives for modest result set sizes.
- **Cheap.** O(N) in the total number of candidate documents.
- **Interpretable.** We can explain why a result ranked where it did.

### Fusion inputs

| Source | Rank domain | Typical top-K |
|---|---|---|
| claude-context chunks | 1..20 (default `limit=20` in path A; 1..K for path C) | 10–20 |
| MemPalace drawers | 1..K | 5–10 |
| MemPalace KG facts | 1..K | 3–5 |

Bounded top-K per source keeps fusion's window finite. In path C the router uses K=10 per source by default, configurable per tool.

### Deduplication before fusion

Fusion can double-count when two sources yield overlapping content:

- A **chunk** and a **memory** that both mention the same function name: these are different kinds, do not dedupe — they add distinct value.
- Two **chunks** from different embedding runs (impossible in a single query, but possible across cached paths): dedupe on `(relative_path, start_line, end_line)`.
- Two **memories** with the same `drawer_id`: dedupe on `drawer_id`.
- A **fact** and a **memory** where the memory's drawer id matches `triples.source_drawer_id` (02 §4 schema): keep both, but mark the fact's `corroborated_by` field to point at the memory.

### Tie-breaking

When two results have the same RRF score (common with small K):

1. Prefer the one anchored to a live symbol (from the Link Layer).
2. Then prefer the one with more recent `created_at` (newer wins).
3. Then lexicographic on content prefix.

### Alternatives considered (and rejected for v1)

- **Learning-to-rank.** Requires labeled data. Out of scope for v1; revisit at M5.
- **Weighted sum after min-max normalization.** Sensitive to outliers; RRF's rank basis is more robust to score drift from any single upstream.
- **Borda count.** Similar properties to RRF but without the `k` smoothing; smaller result sets punish tail items too much.

## 3. Decision table — query features → path

The classifier is a small rule cascade, evaluated top-to-bottom. First match wins.

| # | Condition on the query | Path | Why |
|---|---|---|---|
| 1 | Query matches `^([A-Z][A-Za-z0-9_]*\.)*[a-z_][A-Za-z0-9_]*$` (symbol-ish identifier, one path component) | **B** — Precision-First | Clearly a symbol lookup; don't spend embedding cost. |
| 2 | Query contains `file:<path>` or `file_path=` and a line number | **B** — Precision-First | Caller knows location; Serena resolves. |
| 3 | Query starts with `why `, `who decided`, `history of`, `contradict` | **C** — Fusion (memory-weighted) | Decision / history questions — memory + KG are mandatory. Fuse with K_code=5, K_mem=10, K_facts=5. |
| 4 | Query contains `implement`, `where in code`, `find code that`, `similar to` | **A** — Discovery-to-Precision | Code intent; start with vector search, refine with symbols, no mandatory memory join. |
| 5 | Query contains ≥2 distinct entity-shaped tokens (Capitalized proper nouns or quoted phrases) AND no code-intent keywords | **C** — Fusion (memory-weighted) | Cross-topic — fuse. |
| 6 | Query is ≤3 tokens | **A** — Discovery-to-Precision | Too short to benefit from fusion; let vector search lead. |
| 7 | Default | **C** — Fusion (balanced, K_code=K_mem=10, K_facts=5) | Safe default. |

The classifier is implemented in `engram.router.classifier` and is deliberately transparent: every tool response includes `meta.path_used` so downstream debugging is mechanical.

## 4. Entity extraction for KG queries (Path C step 1)

The KG query needs one or more entity names, not a full sentence. The extractor is simple-by-design:

1. Tokenize the query.
2. Retain tokens that are: capitalized (proper nouns), in double quotes, or match symbol-ish identifier regex (from §3 rule 1).
3. Deduplicate, lowercase-normalize per MemPalace's `_entity_id()` rules (02 §4): `lower().replace(' ', '_').replace("'", '')`.
4. Send the top 3 normalized entities to `mempalace_kg_query` (one call each, in parallel).

No NER model, no spaCy dependency. If this turns out to under-recall in practice, upgrade in M5.

## 5. Caching strategy

Engram hits three subprocess MCP clients per call in path C. Even at stdio's fast ~1 ms round trip, a cold path-C query is ~15 MCP calls. Caching matters.

### 5.1 Cache layers (innermost to outermost)

1. **Router-local in-memory LRU** — per-tool, per-process. Key = `(tool_name, normalized_args_json)`. TTL = 60 s. Size = 1024 entries. Evicts on Link Layer event `symbol.renamed`, `memory.written`, or `chunk.generation_advanced` for matching paths (doc 05 §6.1).
2. **SQLite materialized anchors** (the Link Layer itself). These are treated as a cache of joins across upstream data; no separate invalidation logic needed beyond the Link Layer's event-driven updates (doc 05).
3. **No Redis, no cross-process cache in v1.** Scope-cut.

### 5.2 Cache keys — canonicalization rules

To keep the LRU hit-rate sane, args are canonicalized before hashing:

- Paths normalized to forward-slash + project-relative (same rule as doc 05).
- Numeric fields stringified with no leading zeros.
- Booleans canonicalized to `"true"` / `"false"`.
- Object keys sorted alphabetically before serialization.

### 5.3 TTL choices and why

| Tool | TTL | Reason |
|---|---|---|
| `vec.search_code` | 60 s | Chunks update at the 5-min claude-context tick; 60 s is comfortably less. |
| `code.find_symbol` | 30 s | Symbol state changes are fast; keep TTL short. |
| `code.find_referencing_symbols` | 30 s | Same. |
| `mem.search` | 120 s | Memories change less frequently than code; longer TTL. |
| `mem.kg_query` | 300 s | KG churn is slow; 5-min TTL is safe. |
| Fused results (`engram.why`, etc.) | 60 s | Conservative — min of component TTLs. |

### 5.4 Invalidation by event

Subscribed to the Link Layer's hook bus (doc 05 §6):

- `symbol.renamed` or `symbol.moved` on `symbol_id X` → invalidate any cache key whose args mention X's old or new `name_path` or `relative_path`.
- `memory.written` with `drawer_id D` → invalidate any cache key whose result contained D.
- `chunk.generation_advanced` with `changed_paths P` → invalidate any cache key whose args contain a path in P, or whose result contains a chunk in P.

Implementation note: the LRU tracks a reverse index `path → keys_referencing` to make invalidation O(matches). Avoid full scans.

## 6. Error behavior

Each path defines what to do when an upstream fails.

### Path A failures

| Failure | Behavior |
|---|---|
| claude-context returns error or empty | Return `{kind: "chunk", content: "", error: "vector-index-empty"}` + continue the path (Serena still runs if an anchor hit exists). If no fallback, return empty with `meta.error`. |
| Serena unavailable | Return chunks without symbol resolution; mark `meta.path_degraded="no-precision"`. |
| MemPalace unavailable | Skip enrichment; mark `meta.path_degraded="no-memory"`. |

### Path B failures

| Failure | Behavior |
|---|---|
| Serena cannot resolve the symbol | Query the Link Layer's `symbol_history` for near-matches; return `{suggestions: [...]}` and `meta.error="symbol-not-found"`. |
| `find_referencing_symbols` times out | Return `{references: [], partial: true}`. |

### Path C failures

| Failure | Behavior |
|---|---|
| One of three sources fails | RRF over the remaining two; mark `meta.sources_used`. |
| Two of three fail | Return results from the surviving source with a `meta.path_degraded` flag; do not error. |
| All three fail | Return `{results: [], meta.error: "all-sources-unavailable"}`. HTTP-equivalent 503. |

**Never raise uncaught exceptions to the MCP client.** Doc 07's tool outputs always carry a `meta` field with `error` and `path_degraded` signals so downstream agents can reason about trust.

## 7. Performance budgets

Target per-path latency (P50) on a warm cache, single workspace, medium codebase (10k files, 100k chunks, 1k memories):

| Path | Budget | Dominant cost |
|---|---|---|
| A | 120 ms | One `vec.search_code` (~80 ms) + anchor lookups in SQLite (~5 ms) + optional `get_symbols_overview` on cache miss (~20 ms) |
| B | 80 ms | One `find_symbol` (~40 ms) + one `find_referencing_symbols` (~30 ms) + SQLite anchor join (~5 ms) |
| C | 250 ms | Three parallel fan-out calls (max ~150 ms) + RRF (<5 ms) + enrichment (~50 ms) + SQLite joins |

Cold cache: expect 2–3× these numbers. Numbers are budgets, not measured; doc 10's M2 exit criterion verifies them.

## 8. Streaming / progressive response

For path C in particular, the 250 ms budget is enough that streaming is not worth v1's complexity. If user experience demands it later (M5):

- Fan out immediately, emit a `results_partial` event after each source returns, emit `results_final` after RRF.
- The MCP protocol supports server-initiated notifications; no architectural change required.

Not in scope for v1.

## 9. Observability

Every router response carries a `meta` envelope:

```json
{
  "meta": {
    "path_used": "A" | "B" | "C",
    "path_degraded": null | "no-precision" | "no-memory" | "all-sources-unavailable",
    "sources_used": ["vec", "mem"],
    "cache_hits": ["vec.search_code"],
    "anchor_cache_miss_count": 2,
    "latency_ms": 137,
    "error": null
  }
}
```

Downstream agents (and the user) can observe trust characteristics without re-implementing them. Dashboards in M5 can scrape these envelopes.

## 10. Implications for downstream docs

- **Doc 07** (MCP surface) documents the `meta` envelope as part of every Engram tool's output shape.
- **Doc 08** (feature mapping) classifies each G-feature into path A / B / C and names the fusion variant.
- **Doc 10** (roadmap) makes the budgets in §7 the M2 exit criteria.

## Assumptions

- `k=60` for RRF is the default from the original paper; if tuned against real workloads later, it should never have to change by more than a factor of 2. Not load-bearing for v1.
- Entity extraction simplicity (§4) is sufficient for the queries the router classifies into path C. If recall on KG-joined results is poor, M5 upgrades the extractor.
- LRU cache TTLs are rough defaults. M2 benchmarks will calibrate them.
- "Stdio MCP round trip ~1 ms" is a ballpark. If measured higher, the path-C parallel fan-out still dominates and budgets hold.

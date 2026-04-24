# 03 — Upstream Inventory: claude-context

> Status: **draft**. Cited investigation of the claude-context repo at `/Users/zaghloul/Projects/accelerate-workspace/claude-context/`. Version `0.1.8`, MIT. **TypeScript / Node monorepo** — not Python. Every structural claim carries a `claude-context/path:line` citation.

claude-context (Zilliz) is a semantic code-search engine built on tree-sitter chunking + Milvus vector search, exposed through an MCP server. It is **not** an importable Python library; a Python consumer must run it as a subprocess over MCP stdio.

## 1. Entrypoints

- **MCP server main.** `packages/mcp/src/index.ts:1-307`. Shebang at `:1` (`#!/usr/bin/env node`) makes the compiled binary directly runnable via `npx`. All `console.*` is redirected to stderr (`:5-14`) to keep stdout as pure JSON-RPC. The `ContextMcpServer` class (`:34`) initializes components and calls `server.connect(transport)` at `:261`.
- **Core library public API.** `packages/core/src/index.ts:1-6` re-exports: `splitter`, `embedding`, `vectordb`, `types`, `context` (main `Context` class), `sync/synchronizer` (`FileSynchronizer`), and `utils`.
- **npm bin.** `packages/mcp/package.json:8` — `"bin": "dist/index.js"`. Installed globally as `claude-context-mcp` or invocable via `npx @zilliz/claude-context-mcp`.
- **Env configuration.** `packages/mcp/src/config.ts:111-147` (`createMcpConfig()`) reads via `envManager` (imported from core at `:1`). Supported vars (logged at `:114-122`):
  - `EMBEDDING_PROVIDER` (default `OpenAI`), `EMBEDDING_MODEL`
  - `OPENAI_API_KEY`, `VOYAGEAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `OLLAMA_MODEL`, `OLLAMA_HOST`
  - `MILVUS_ADDRESS`, `MILVUS_TOKEN`
  - `CODE_CHUNKS_COLLECTION_NAME_OVERRIDE`
- `envManager` falls back to `~/.context/.env` for global config per `docs/getting-started/environment-variables.md:5-6`.

## 2. MCP surface — complete and exhaustive (4 tools)

Tools are registered in a single `ListTools` handler (`packages/mcp/src/index.ts:121-227`) and dispatched by a `CallTool` handler (`:230-246`).

| # | Tool | Registration | Inputs (Zod) | Output | Behavior |
|---|---|---|---|---|---|
| 1 | `index_codebase` | `packages/mcp/src/index.ts:125-163` | `path: string`, `force?: boolean`, `splitter?: "ast"\|"langchain"`, `customExtensions?: string[]`, `ignorePatterns?: string[]` | text + `isError` | Recursively index a codebase with AST or LangChain splitter; creates a Milvus collection. Detects conflicts and requires `force` to re-index. |
| 2 | `search_code` | `packages/mcp/src/index.ts:166-195` | `path: string`, `query: string`, `limit?: number (1–50, default 10)`, `extensionFilter?: string[]` | text (formatted results) | Semantic (or hybrid) search; returns up to `limit` ranked results with file location, language, score. |
| 3 | `clear_index` | `packages/mcp/src/index.ts:198-210` | `path: string` | text | Drop the Milvus collection + delete its on-disk snapshot. |
| 4 | `get_indexing_status` | `packages/mcp/src/index.ts:212-224` | `path: string` | text with progress % or status (`completed`, `indexing`, `indexfailed`) | Current indexing progress for a codebase. |

**Total: 4 tools.** All handlers live in `ToolHandlers` (`packages/mcp/src/handlers.ts:8-50`): `handleIndexCodebase` (`:307-598`), `handleSearchCode` (`:599-760`), `handleClearIndex` (`:761-803`), `handleGetIndexingStatus` (`:804-846`).

## 3. AST chunking strategy

### Languages supported

`packages/core/src/splitter/ast-splitter.ts:14-26` — ten tree-sitter grammars, statically imported at `:5-13`:

- JavaScript / TypeScript (`.js`, `.jsx`, `.ts`, `.tsx`)
- Python (`.py`)
- Java (`.java`)
- C / C++ (`.c`, `.h`, `.cpp`, `.hpp`)
- Go (`.go`)
- Rust (`.rs`)
- C# (`.cs`)
- Scala (`.scala`)

Extension → parser + splittable node type mapping in `getLanguageConfig()` (`:86-107`). Full list of recognized variants in `isLanguageSupported()` (`:263-269`).

### Chunk boundaries

- Default chunk size **2500 characters** with **300-character overlap** (`ast-splitter.ts:28-41`).
- Splittable nodes = typical function/class/method boundaries per language config.
- When an AST node exceeds `chunkSize`, the splitter falls back to line-based accumulation until the size limit is reached (`:180-226`).
- On parse error or unsupported language, the splitter falls back to `LangChainCodeSplitter` (character-based) — imported at `:40`, used at `:44-74`.

### Chunk contents

A chunk (`ast-splitter.ts:109-162`) contains:

- **Code text only** — no surrounding context (no parent class/function hint attached).
- Metadata (`:130-135`): `startLine`, `endLine` (1-indexed), `language` (e.g. `"python"`), optional `filePath`.

This is worth highlighting for Engram: the vector index loses semantic context beyond node body. The enclosing function name is not embedded. For symbol-anchored search (Link Layer), Engram must add this via its own anchor store (doc 05), not rely on claude-context embeddings alone to know "this chunk belongs to function X".

## 4. Embedding providers

Five are implemented (`packages/core/src/embedding/*.ts` + OpenRouter in `packages/mcp/src/embedding.ts`). Factory `createEmbeddingInstance()` at `packages/mcp/src/embedding.ts:5-79`:

| Provider | File | Default model | Auth | Notes |
|---|---|---|---|---|
| OpenAI | `packages/core/src/embedding/openai-embedding.ts` | `text-embedding-3-small` | `OPENAI_API_KEY`, optional `OPENAI_BASE_URL` | Uses `openai` SDK (core `package.json:23`, `^5.1.1`). |
| VoyageAI | `packages/core/src/embedding/voyageai-embedding.ts` | `voyage-code-3` | `VOYAGEAI_API_KEY` | `voyageai` `^0.0.4`. |
| Gemini | `packages/core/src/embedding/gemini-embedding.ts` | `gemini-embedding-001` | `GEMINI_API_KEY`, optional `GEMINI_BASE_URL` | `@google/genai` `^1.9.0`. |
| Ollama | `packages/core/src/embedding/ollama-embedding.ts` | configured per `OLLAMA_MODEL` | none (local) | Local endpoint, default `http://127.0.0.1:11434`. **Zero-API option.** |
| OpenRouter | `packages/mcp/src/embedding.ts:50-63` | per config | `OPENROUTER_API_KEY` | Reuses `OpenAIEmbedding` with `https://openrouter.ai/api/v1` base URL. |

Provider selection via `EMBEDDING_PROVIDER` env var (`packages/mcp/src/config.ts:127`). All providers extend the abstract `Embedding` class (`packages/core/src/embedding/base-embedding.ts:10-76`) with: `embed(text)`, `embedBatch(texts)`, `getDimension()`, `getProvider()`.

## 5. Milvus integration

### SDK

`@zilliz/milvus2-sdk-node@^2.5.10` (`packages/core/package.json:17`).

### Collection schema (standard, non-hybrid)

`packages/core/src/vectordb/milvus-vectordb.ts:215-304`:

| Field | Type | Max len / dim | Index |
|---|---|---|---|
| `id` | VarChar | 512 | Primary key |
| `vector` | FloatVector | `dimension` (embedder-dependent) | AUTOINDEX, metric `COSINE` |
| `content` | VarChar | 65535 | — |
| `relativePath` | VarChar | 1024 | — |
| `startLine` | Int64 | — | — |
| `endLine` | Int64 | — | — |
| `fileExtension` | VarChar | 32 | — |
| `metadata` | VarChar | 65535 | — |

Index created at `:283-292` with `index_type: 'AUTOINDEX'`, `metric_type: MetricType.COSINE`. AUTOINDEX resolves to HNSW for float vectors. Sparse-vector hybrid search is opt-in via `createHybridCollection()` (not the default path).

### Collection naming

`packages/core/src/context.ts:180-230`:

- Base: `code_chunks_<md5(absolute_codebase_path)>`.
- With `CODE_CHUNKS_COLLECTION_NAME_OVERRIDE`: `code_chunks_<sanitized_override>_<pathHash>` — the path hash is *always appended*, even with override, to keep multi-codebase usage distinct.
- Hybrid variant: `hybrid_code_chunks_<override>_<pathHash>`.

### Self-hosted Milvus — supported

`MilvusConfig` (`packages/core/src/vectordb/milvus-vectordb.ts:40-50`) accepts `address`, `token`, `username`, `password`, `ssl`. If only `token` is supplied, `ClusterManager.getAddressFromToken()` resolves a Zilliz Cloud endpoint. If `address` is given (e.g. `localhost:19530`), it is used as-is.

**No `docker-compose.yml` is bundled in this repo.** `docs/getting-started/prerequisites.md:37-39` points users at the official Milvus Docker guide (`https://milvus.io/docs/install_standalone-docker-compose.md`). Doc 09 needs to produce a minimal compose for Engram's privacy-sensitive users — this is an Engram deliverable, not a claude-context one.

## 6. Incremental re-index — **VERDICT: periodic (5 min), Merkle-DAG based, requires MCP server running**

This is the single claude-context finding most likely to force an Engram scope change.

### Mechanism

`packages/core/src/sync/synchronizer.ts:1-31` — `FileSynchronizer` maintains a Merkle DAG of SHA-256 file hashes:

1. On each sync, scan the tree and hash every file (`:34-42`).
2. Build a Merkle tree (`:226`).
3. Compare to the stored tree (`:237`).
4. Return `{added, removed, modified}` (`:239`).

### Snapshot storage

One snapshot file per codebase at `~/.context/merkle/<md5-of-codebase-path>.json` (`synchronizer.ts:24-31`). Loaded on `initialize()` (`context.ts:382`).

### Incremental apply (`context.ts:369-436`, `reindexByChange()`)

- Removed files → `deleteFileChunks()` (`:408-411`): delete all chunks where `relativePath == file`.
- Modified files → delete old chunks, re-index (`:414-417, 420-429`).
- Added files → index new chunks (`:420-429`).

### Scheduling

`packages/mcp/src/sync.ts:114-142` — `startBackgroundSync()`:

- Initial sync after 5 seconds (`:118-132`).
- **Periodic sync every 5 minutes** (`setInterval`, `:135-139`, literal `5 * 60 * 1000`).
- No file-watch (`chokidar` / `fs.watch` absent from imports). No git hook.

### Failure handling

`sync.ts:77-96` — errors caught and logged; if the error string contains `"Failed to query collection"`, the snapshot is deleted to force a clean re-index next cycle. Loop continues.

### Implications for Engram

- Any Engram feature that needs "near-real-time" freshness on the vector index must add its own trigger (chokidar watcher OR git post-commit hook) and invoke `reindexByChange()` sooner than the 5-minute tick.
- Engram cannot rely on claude-context to emit "a file changed" events — the "discovery" only happens during the 5-minute tick. Doc 05 anchor-freshness budget must account for this.
- The MCP tool surface has **no** "sync now" / "re-index this one file" primitive. This is a candidate upstream PR (PR-CC-1 in doc 10), and in the meantime Engram must accept a ≤5-minute staleness window or invoke a forced `reindexByChange` via the core Context API directly (not via MCP).

## 7. Search result shape

`packages/core/src/types.ts:7-14` — `SemanticSearchResult`:

```ts
{
  content: string;       // full code chunk text
  relativePath: string;  // e.g. "src/lib/utils.ts"
  startLine: number;     // 1-indexed
  endLine: number;       // 1-indexed
  language: string;      // e.g. "python"
  score: number;         // 0.0–1.0 (cosine similarity for COSINE metric)
}
```

Constructed at `context.ts:530-537` (regular) and `context.ts:557-565` (hybrid). Milvus returns results sorted descending by score (`milvus-vectordb.ts:371-419`). MCP handler formats results as human-readable text (`handlers.ts:742-750`).

## 8. Public JS API surface

`packages/core/src/index.ts:1-6`:

```ts
export * from './splitter';             // AstCodeSplitter, LangChainCodeSplitter, Splitter
export * from './embedding';            // Embedding, OpenAI/Voyage/Gemini/Ollama embeddings
export * from './vectordb';             // VectorDatabase, MilvusVectorDatabase, VectorDocument, SearchOptions
export * from './types';                // SemanticSearchResult, SearchQuery
export * from './context';              // Context (main class)
export * from './sync/synchronizer';    // FileSynchronizer
export * from './utils';                // envManager
```

`Context` (`packages/core/src/context.ts:100-150`) constructor accepts `embedding?`, `vectorDatabase?`, `codeSplitter?`, `supportedExtensions?`, `ignorePatterns?`, `customExtensions?`, `customIgnorePatterns?`, `collectionNameOverride?`. Public methods: `index()`, `semanticSearch()`, `reindexByChange()`, `hasIndex()`, `clearIndex()`.

Stability signals: version `0.1.8` — pre-1.0, API may break on minor bumps. MIT license. No CHANGELOG at the repo root; no deprecation markers in code.

## 9. Self-hosted Milvus — minimal viable path

1. Docker + Docker Compose installed.
2. Download Milvus `docker-compose.yml` from `https://milvus.io/docs/install_standalone-docker-compose.md` (**not bundled in claude-context**).
3. `docker-compose up -d` → Milvus at `localhost:19530`.
4. Configure claude-context:
   ```bash
   export MILVUS_ADDRESS=localhost:19530
   export EMBEDDING_PROVIDER=Ollama
   export OLLAMA_HOST=http://127.0.0.1:11434
   export OLLAMA_MODEL=nomic-embed-text
   npx @zilliz/claude-context-mcp@latest
   ```
5. Combined with Ollama for embeddings, the pipeline is fully local — zero outbound network calls after model download.

Engram's doc 09 should ship a `compose.yaml` that bundles Milvus + Ollama + claude-context-mcp for one-shot install.

## 10. On-disk state (outside Milvus)

Two local files per codebase, both under `~/.context/`:

- `~/.context/mcp-codebase-snapshot.json` (`packages/mcp/src/snapshot.ts:24`). **V2 format** (`packages/mcp/src/config.ts:64-71`):
  ```json
  {
    "formatVersion": "v2",
    "codebases": {
      "/abs/path": {
        "status": "indexed|indexing|indexfailed",
        "indexedFiles": 123,
        "totalChunks": 456,
        "indexStatus": "completed|limit_reached",
        "lastUpdated": "2026-04-24T…"
      }
    },
    "lastUpdated": "…"
  }
  ```
  V1 (array of paths) auto-migrated on load (`snapshot.ts:30-92`).
- `~/.context/merkle/<md5>.json` — file-hash snapshot per codebase (§6). Deleted on `clearIndex` (`context.ts:605` → `FileSynchronizer.deleteSnapshot()`).

Snapshot corruption handling: if JSON parse fails, the old snapshot is ignored and codebases are treated as un-indexed. **Issue #295** documented at `handlers.ts:25-50`: writing `{indexedFiles:0, totalChunks:0, status:"completed"}` for an unknown collection previously caused an infinite re-index loop; validation code now prevents it.

## 11. Failure modes

| Scenario | Location | Behavior |
|---|---|---|
| Milvus unreachable at init | `milvus-vectordb.ts:40-50` | Constructor can hang on bad address; errors surface on first operation. No constructor timeout. |
| Collection does not exist | `context.ts:472-476` | `hasCollection()` returns false; `semanticSearch()` logs warning, returns `[]`. |
| Embedding API rate-limited | provider SDK | Error bubbles to MCP handler → error text in response. No automatic backoff. |
| File unparseable | `ast-splitter.ts:70-73` | Fall back to LangChain splitter (logged). |
| Unsupported language | `ast-splitter.ts:46-50` | LangChain splitter path (logged). |
| Sync cycle Milvus error | `sync.ts:77-96` | Catch + log; on `"Failed to query Milvus"`, delete snapshot to force re-index next cycle. |
| Collection limit (Zilliz Cloud) | `vectordb/types.ts:151-154` | Distinct `COLLECTION_LIMIT_MESSAGE` error. |
| Snapshot corrupted | `snapshot.ts:30-92` | Ignored; codebases treated as un-indexed. Issue #295 validation prevents the infinite-loop footgun. |

Retry: only collection-load retries with exponential backoff (`milvus-vectordb.ts:175-213`, up to 5×). Search / insert do not retry.

## 12. Licensing & deps

### Licenses

- Repo: MIT (`LICENSE`).
- All listed runtime deps are MIT or Apache 2.0 (verified per `package.json` license fields):
  - Core (`packages/core/package.json:15-36`): `@google/genai` (Apache 2.0), `@zilliz/milvus2-sdk-node` (Apache 2.0), `faiss-node` (MIT), `fs-extra` (MIT), `glob` (ISC), `langchain` (MIT), `ollama` (MIT), `openai` (MIT), `tree-sitter` + language grammars (MIT), `typescript` (Apache 2.0), `voyageai` (MIT).
  - MCP (`packages/mcp/package.json:20-24`): `@zilliz/claude-context-core` (workspace), `@modelcontextprotocol/sdk` (MIT), `zod` (MIT).
- **No GPL / AGPL / SSPL / Commons Clause** observed.

## 13. Python consumer's reality

claude-context has no published Python package. A Python consumer (Engram) integrates via MCP stdio subprocess:

```python
import subprocess, os
env = os.environ.copy()
env.update({
    "OPENAI_API_KEY": ...,      # or other provider creds
    "MILVUS_ADDRESS": "localhost:19530",
    "EMBEDDING_PROVIDER": "OpenAI",
})
proc = subprocess.Popen(
    ["npx", "@zilliz/claude-context-mcp@latest"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    env=env,
)
# speak JSON-RPC 2.0 on stdin/stdout; tail stderr for logs
```

### Runtime requirements

- Node.js **≥ 20.0.0, < 24.0.0** (`package.json:41-43`, README notes Node 24 incompatibility).
- `npm` or `pnpm` available so `npx` can fetch the package.
- Access to Milvus (self-hosted or Zilliz Cloud).
- Embedding provider creds (unless using Ollama, which is local).

### Critical: stdout / stderr separation

MCP protocol requires **pure JSON-RPC on stdout**. claude-context redirects all its own `console.log` to stderr (`packages/mcp/src/index.ts:5-14`). An Engram Python client that mixes stderr into the read loop will break JSON parsing — it must read the two streams separately.

### Cold-start overhead

~2–5 s (Node.js JIT + Milvus connection). Engram should start claude-context-mcp once at service init and keep it alive across requests, not spawn per request.

## 14. Implications for Engram (feeds into docs 04, 05, 06, 08, 09, 10)

- **Vector search is the "chunk" primitive.** `search_code` gives Engram the discovery layer. Fair assumption: most natural-language queries in the Retrieval Router's "discovery-first" path start here (doc 06).
- **Anchor fidelity requires augmentation.** Chunks carry `relativePath`, `startLine`, `endLine`, and `language` but not the enclosing symbol name or function signature. The Link Layer's `symbol↔chunk` anchor (doc 05) fills this in by calling Serena's `get_symbols_overview` when a chunk is indexed.
- **Incremental index is the bottleneck.** 5-minute polling is the default. Engram must either accept this window or install its own trigger (watcher or git hook) that calls `context.reindexByChange()` through the core JS API (not MCP) — which means Engram needs a small Node shim if it wants sub-minute freshness. This is logged in doc 10 as M1 scope.
- **Language-split implication.** Engram is Python; claude-context is Node. Direct JS API access requires a Node subprocess either way. The default Engram integration shape (doc 04's Shape Decision) runs claude-context as `@zilliz/claude-context-mcp` over stdio. Any feature needing `reindexByChange` outside the 5-minute tick would need a second thin Node shim (small, ≤100 LOC).
- **Milvus self-host is required for privacy-sensitive installs.** Engram's doc 09 must ship a single `compose.yaml` bundling Milvus + Ollama + claude-context-mcp so the on-prem story is one command.
- **No collision with Serena or MemPalace on tool names** (see doc 07): `index_codebase`, `search_code`, `clear_index`, `get_indexing_status` are all unique. But `search_code` vs Serena's `search_for_pattern` require explicit routing docs to prevent user confusion.

## Assumptions

- "AUTOINDEX resolves to HNSW for float vectors" is a Milvus runtime behavior, not a claude-context guarantee. If Milvus changes its AUTOINDEX resolution, Engram's latency assumptions in doc 06 might shift. Not load-bearing, but flagged.
- Node 24 incompatibility is cited from the README (`packages/package.json:41-43` says `">=20.0.0"` with no upper bound; the cap is documentation-level, not an enforced `engines` version). Engram's install doc (09) should restate this cap.
- `hybrid_code_chunks_*` collection variants are mentioned but hybrid search is not enabled in the default MCP path (`search_code` uses regular `semanticSearch`). Doc 06's fusion algorithm should not assume hybrid dense+sparse from claude-context unless Engram opts in.

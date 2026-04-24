# Engram — Project Context

## Mission

Engram is a unified coding-agent substrate that composes three open-source MCP servers into one MCP-addressable system:

- **Serena** — LSP-backed symbol-level code understanding (Python, MIT).
- **MemPalace** — verbatim episodic memory + SQLite temporal knowledge graph (Python, MIT).
- **claude-context** — AST-chunked vector code search backed by Milvus (TypeScript, MIT).

Engram adds two new pieces of substance on top:

1. **Link Layer** — anchor store connecting symbols ↔ memories ↔ chunks; keeps anchors correct as code moves.
2. **Retrieval Router** — query orchestration that picks symbol / memory / vector / fused paths and returns one composed answer.

Engram exposes a unified MCP surface (`code.*`, `mem.*`, `vec.*`, `engram.*`) to downstream agent clients (Claude Code, Cursor, Claude Desktop).

## Shape Decision

**Shape-A (MCP-client orchestrator).** Engram is a Python MCP server; internally an MCP *client* to three long-lived subprocesses (`serena start-mcp-server`, `mempalace-mcp`, `npx @zilliz/claude-context-mcp`). Rationale in planning doc `04-integration-surface-map.md` §6.

Rule: **upstream code must not be modified**. Engram integrates via each upstream's public MCP surface, WAL file (MemPalace), and CLI — never by monkeypatching.

## Stack

- **Language:** Python 3.11+ (matches Serena's minimum).
- **Packaging:** PyPI wheel; `pip install -e .` in a virtualenv.
- **Anchor store:** SQLite WAL-mode, single-writer, in `.engram/anchors.sqlite`.
- **Vector store:** Milvus (standalone via compose); embeddings via Ollama default.
- **MCP:** stdio transport; proxy + router + `engram.*` namespace.
- **Process topology:** 4 processes — Engram + Serena + MemPalace + claude-context.
- **Configuration:** `.engram/config.yaml` (per-workspace), `~/.engram/` (user).
- **Logs:** `.engram/logs/audit.jsonl` (M4+).

## Conventions

- **Every structural claim in planning docs carries `repo:line` citations.** Keep this hygiene in specs: if a requirement references upstream behavior, cite the upstream file/line where possible.
- **Scenarios use Given/When/Then.** WHEN = trigger or condition. THEN = observable outcome. No vibes-based criteria.
- **Exit criteria are mechanical.** Prefer `sqlite3 ... '.schema'` matches, `jq 'length'`, `pytest-benchmark` thresholds over subjective checks.
- **Errors are stable codes.** `symbol-not-found`, `drawer-not-found`, `upstream-unavailable`, `timeout`, `invalid-input`, `fact-checker-unavailable`, `all-sources-unavailable`, `consistency-state-hint`.
- **Responses carry `meta` envelope.** `{result, meta}` on success; `{error: {code, message, details?}, meta}` on failure.

## Namespaces

| Namespace | Semantics | Backed by |
|---|---|---|
| `code.*` | Symbol-level code | Serena (proxy) |
| `mem.*` | Episodic memory + KG | MemPalace (proxy) |
| `vec.*` | Vector code search | claude-context (proxy) |
| `engram.*` | Composed / Link Layer | Engram (new) |

Approx 80 tools total. `engram.*` = 8 new tools (`anchor_memory_to_symbol`, `anchor_memory_to_chunk`, `why`, `where_does_decision_apply`, `symbol_history`, `contradicts`, `reconcile`, `health`).

## Roadmap

v1 = M0–M3, 14–18 engineer-weeks.

- **M0** — Shell + topology (4–5 wk). 4-process supervision, proxy-only, `engram.health` only.
- **M1** — Link Layer + WAL tailer (3–4 wk). Anchor store + rename wrapper + explicit anchor tools.
- **M2** — Retrieval Router + RRF fusion (4–5 wk). `engram.why`, `engram.symbol_history`, cache.
- **M3** — J4/J5 features (3–4 wk). `engram.contradicts`, `engram.where_does_decision_apply`, reconciler.
- **M4** — Fast sync + confidence decay + audit (2–3 wk). Chokidar shim, decay, audit log.
- **M5** — UI / federation / polish (open-ended).

## Planning artifacts

All authoritative design lives in `engram/0*-*.md` (13 docs, ~27.9k words):

- `00-README.md` — bundle overview, reading order.
- `01`–`03` — upstream inventories (Serena / MemPalace / claude-context) with `repo:line` citations.
- `04` — integration surface map + Shape Decision.
- `05` — Link Layer design (7-table SQLite schema, 3 unique partial indices).
- `06` — Retrieval Router + RRF k=60 fusion.
- `07` — MCP surface (namespaces, collisions, error envelope).
- `08` — G1–G22 feature mapping (12 keep / 6 defer / 4 cut).
- `09` — repo layout + compose.yaml + `engram init` flow.
- `10` — M0–M5 roadmap with mechanical exit criteria.
- `11` — risks + open questions (18 + 14).
- `12` — glossary.

Specs in `openspec/specs/` are the source of truth for behavior; planning docs are the source of truth for rationale and citations.

## Non-goals

- Not an AI IDE, AI agent, or coding tool itself — it orchestrates existing ones.
- Not hosted / multi-tenant in v1 — single-workspace, local-first.
- No upstream modification. Features that require patching Serena / MemPalace / claude-context internals are out of scope or ship as optional upstream PRs.
- No verbatim-memory mutation. MemPalace drawers are append-only; Engram never rewrites drawer content.

# Engram Planning Bundle

> Status: **draft — bundle complete**. Thirteen docs totaling ~27.9k words. Every structural claim in 01–03 carries `repo:line` citations; 04–12 build on those with inline cross-references. Random-sampled 7 of the cited lines during authoring — all verified. Ready for reviewer pass.

---

## What Engram is

Engram is a proposed unified coding-agent substrate that composes three existing open-source projects into a single MCP-addressable system:

- **Serena** — LSP-backed symbol-level code understanding (Python, MIT).
- **MemPalace** — verbatim episodic memory + SQLite knowledge graph for AI agents (Python, MIT).
- **claude-context** — AST-chunked vector code search backed by Milvus (TypeScript/Node, MIT).

Engram adds two new pieces of substance on top of the three upstreams:

1. **A Link Layer** — an anchor store that connects symbols (from Serena) to memories (from MemPalace) to code chunks (from claude-context), and keeps those anchors correct as code moves.
2. **A Retrieval Router** — query orchestration that chooses among symbol search, memory search, vector search, or a fusion of them, and returns a single composed answer.

Engram also exposes a unified MCP surface (`code.*`, `mem.*`, `vec.*`, `engram.*`) to downstream agent clients (Claude Code, Cursor, Claude Desktop, etc.).

---

## Who should read what

| Reader | Read first |
|---|---|
| Reviewer deciding whether this plan holds up | `01`, `02`, `03`, `04` — the cited inventories and the surface map |
| Engineer building the Link Layer | `05`, plus `01`/`02`/`03` for upstream call references |
| Engineer building the Retrieval Router | `06`, plus `04` for the join points |
| Client integrator (MCP configuration) | `07`, `09` |
| Product / planning — scope & timeline | `08` (feature fate), `10` (phases), `11` (risks & open questions) |
| Any reader confused by a term | `12` (glossary) |

---

## Document status

| # | File | Audience | Words | Status |
|---|---|---|---|---|
| 00 | `00-README.md` | All | ~1.0k | draft |
| 01 | `01-upstream-inventory-serena.md` | Reviewer + engineers | ~2.4k | draft |
| 02 | `02-upstream-inventory-mempalace.md` | Reviewer + engineers | ~2.8k | draft |
| 03 | `03-upstream-inventory-claude-context.md` | Reviewer + engineers | ~2.4k | draft |
| 04 | `04-integration-surface-map.md` | Reviewer | ~2.6k | draft — includes Shape Decision (A) |
| 05 | `05-link-layer-design.md` | Engineer | ~3.2k | draft — schema + population + reconciliation |
| 06 | `06-retrieval-router-design.md` | Engineer | ~2.3k | draft — RRF k=60 fusion specified |
| 07 | `07-mcp-surface.md` | Client integrator | ~1.9k | draft — 8 engram.* tools + proxy spec |
| 08 | `08-feature-mapping.md` | Product/planning | ~2.3k | draft — 12 keep / 6 defer / 4 cut |
| 09 | `09-repo-layout-and-setup.md` | Client integrator | ~1.8k | draft — includes compose.yaml |
| 10 | `10-phased-roadmap.md` | Product/planning | ~1.5k | draft — M0–M5 with mechanical exit criteria |
| 11 | `11-risks-and-open-questions.md` | Product/planning | ~1.7k | draft — 18 risks + 14 open questions |
| 12 | `12-glossary.md` | All | ~1.9k | draft |

**Total: ~27.9k words** (target 15k–35k).

Status values: **not started / in progress / draft / reviewed / blocked**. All docs are `draft`; they have not been formally reviewed yet. Blockers (investigation that came up empty and needs a human) are listed below under "What's blocked."

---

## Reading order (for a skeptical reviewer)

1. `01`, `02`, `03` in any order — the cited upstream inventories. These are the ground truth for everything else.
2. `04` — the integration surface map. Builds directly on 01–03 and contains the **Shape Decision** (how the three upstreams are composed).
3. `05`, `06` — the new substance. Schemas, control flow, fusion logic.
4. `07` — the unified MCP surface that clients see.
5. `08` — which of the prior-design features (G1–G22) survive, in what form.
6. `09` — how a team actually installs and configures Engram.
7. `10` — phased rollout with mechanical exit criteria per milestone.
8. `11` — risks and open questions, aggregated from every prior doc.
9. `12` — glossary.

---

## Early findings worth surfacing up front

- **claude-context is TypeScript**, not Python. Engram's integration shape is therefore non-trivial; the decision is made in `04` based on the hook evidence uncovered in `01`–`03`.
- **All three upstreams are MIT-licensed.** No GPL/AGPL exposure observed at the top level. Transitive-tree confirmation lives in each inventory.
- **MemPalace has an explicit plugin-style backend interface** (`mempalace/backends/base.py`) and a Claude-Code-style hook directory (`hooks/`). Both are plausible Engram integration points; `02` verifies their actual contracts.
- **Serena advertises itself as "the IDE for your coding agent"** and exposes symbol-level tools via MCP. Whether it also exposes file-watch / rename events externally — and therefore whether Engram's anchor store can be kept correct without polling — is one of the two most important questions in `01`.

---

## What's blocked

Three investigations came up empty and need a human resolution (full detail in doc 11 under "Investigation blockers"):

- **B1 — MemPalace WAL rotation policy.** `rg "rotate|truncate|rollover|logrotate|os.rename" mempalace/mempalace/mcp_server.py` returned no WAL-rotation logic. Default assumption: append-only-forever. Impact: cursor design in doc 05 §4.2. Resolution: file a question upstream (Q-05-WAL-ROTATION in doc 11).
- **B2 — claude-context `engines` upper bound.** README says Node < 24 but `package.json`'s `engines` field only specifies `>=20.0.0`. Documentation gap in upstream, not a blocker for Engram. Engram enforces the upper bound explicitly in `engram init` (doc 09 §4).
- **B3 — `mempal_precompact_hook.sh` internals.** File inspected for size / contract direction only; deep internals not traced. Not load-bearing for any Engram design in this bundle.

## Decisions made during authoring

- **Shape Decision: A (MCP-client orchestrator)** — doc 04 §6. Rationale: MemPalace's external WAL gives all needed observability; Shape-B's in-process advantage is illusory once upstream modification is forbidden.
- **Fusion algorithm: RRF with k=60** — doc 06 §2. Standard modern rank-fusion; score-scale agnostic; no training required.
- **Anchor store: SQLite, 7 tables, 3 unique partial indices** — doc 05 §2. Single-writer WAL-mode; rejected Postgres, JSONL, and Redis.
- **Feature fate of prior 22-item G-list:** 12 keep / 6 defer / 4 cut — doc 08. G17 (auto-populate KG), G18 (hook takeover), G20 (hosted summarization), G21 (benchmarks) are cut.
- **v1 scope: M0–M3, 14–18 engineer-weeks** — doc 10.

## Review checklist for the reviewer

1. Pick 20 random citations from docs 01–03 by eye (or `rg ":[0-9]+" engram/0[1-3]*.md | shuf -n 20`). Open each in the upstream repo — the cited line should contain the code described in the doc.
2. Cross-check that `engram init` flow in doc 09 §6 actually reaches a `engram.why` call. If any step is missing, mark doc 09 as blocked.
3. Verify doc 10's exit criteria are mechanical (shell-runnable). Any vibe-based criteria fail the bar.
4. Confirm every open question in doc 11 is yes/no. Any open-ended question fails the bar.
5. Challenge the Shape-A decision in doc 04 §6 — if you can find a case where Shape-B or Shape-C is materially better, reopen Q-04-SHAPE.

---

## Conventions used across the bundle

- **Citations.** Every structural claim is cited `repo/relative/path.ext:LINE` or `repo/relative/path.ext:START-END`. Uncited claims are explicitly marked as *Assumption* and live in an `## Assumptions` section at the end of the relevant doc.
- **Contradictions.** Where an upstream README or CLAUDE.md promises behavior the code doesn't implement, the code wins and the contradiction is flagged in the relevant inventory.
- **Complexity estimates.** S (≤ 1 engineer-week), M (1–3 weeks), L (3–6 weeks). Every estimate is justified by a citation to code complexity in the relevant upstream.
- **Keep / cut / defer.** Applied in `08` per feature; each has a one-sentence reason grounded in 01/02/03.

---

*Last updated: this file is re-written at the end of each step to reflect document status and newly discovered blockers.*

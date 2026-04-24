# Engram

Unified coding-agent substrate that composes Serena (symbols), MemPalace (memory + KG), and claude-context (vector search) behind one MCP endpoint, adds a Link Layer that keeps anchors correct across code motion, and a Retrieval Router that fuses retrieval paths with RRF k=60.

## Status

Early development. v1 targets M0–M3 (14–18 engineer-weeks). See `10-phased-roadmap.md` for milestones and `openspec/` for current specs.

## Quickstart

```bash
pip install -e .[dev]
npm install -g @zilliz/claude-context-mcp@0.1.8
docker compose -f deploy/compose.yaml up -d

engram init --embedding-provider Ollama
engram smoke-test
engram mcp   # stdio MCP server
```

Register with your agent client (Claude Code, Cursor, Claude Desktop) — see `09-repo-layout-and-setup.md` §5.

## Layout

```
engram/
├── src/engram/        # Python package
├── deploy/            # compose.yaml (Milvus + Ollama)
├── tests/             # unit + integration + fixtures
├── openspec/          # specs (source of truth for behavior)
└── 00–12-*.md         # planning bundle (source of truth for rationale)
```

## License

MIT.

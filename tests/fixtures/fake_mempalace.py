"""Fake MemPalace-ish MCP server.

Exposes mempalace_get_drawer (drawer lookup), mempalace_status (probe),
mempalace_add_drawer (accepts + echoes drawer payload), and the two KG
mutators used by the rename write-hook (`mempalace_kg_add`,
`mempalace_kg_invalidate`). All calls are logged to a JSONL file at
$FAKE_MEMPALACE_LOG so tests can assert side-effects.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import mcp.types as mcp_types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

DRAWER_DB: dict[str, dict] = {}


def _log(op: str, payload: dict) -> None:
    log_file = os.environ.get("FAKE_MEMPALACE_LOG")
    if not log_file:
        return
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    with Path(log_file).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"op": op, "payload": payload}) + "\n")


async def _main() -> None:
    seed = os.environ.get("FAKE_MEMPALACE_SEED")
    if seed:
        for entry in json.loads(seed):
            DRAWER_DB[entry["drawer_id"]] = entry

    server: Server = Server("fake-mempalace")

    @server.list_tools()
    async def _list() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name="mempalace_status",
                description="probe\nUse when checking liveness.",
                inputSchema={"type": "object"},
            ),
            mcp_types.Tool(
                name="mempalace_get_drawer",
                description="drawer\nPrefer for fetching one drawer.",
                inputSchema={
                    "type": "object",
                    "properties": {"drawer_id": {"type": "string"}},
                    "required": ["drawer_id"],
                },
            ),
            mcp_types.Tool(
                name="mempalace_add_drawer",
                description="add\nPrefer for writing verbatim content.",
                inputSchema={"type": "object"},
            ),
            mcp_types.Tool(
                name="mempalace_kg_add",
                description="kg\nUse when adding triples.",
                inputSchema={"type": "object"},
            ),
            mcp_types.Tool(
                name="mempalace_kg_invalidate",
                description="kg\nUse when invalidating a fact.",
                inputSchema={"type": "object"},
            ),
        ]

    @server.call_tool()
    async def _call(name: str, arguments: dict | None) -> list[mcp_types.TextContent]:
        args = arguments or {}
        _log(name, args)
        if name == "mempalace_status":
            return [mcp_types.TextContent(type="text", text='{"ok": true}')]
        if name == "mempalace_get_drawer":
            did = args.get("drawer_id")
            drawer = DRAWER_DB.get(did)
            if drawer is None:
                raise ValueError(f"drawer not found: {did}")
            return [mcp_types.TextContent(type="text", text=json.dumps(drawer))]
        if name == "mempalace_add_drawer":
            drawer_id = args.get("drawer_id", f"auto-{len(DRAWER_DB)}")
            DRAWER_DB[drawer_id] = {"drawer_id": drawer_id, **args}
            return [
                mcp_types.TextContent(
                    type="text", text=json.dumps({"drawer_id": drawer_id})
                )
            ]
        if name in ("mempalace_kg_add", "mempalace_kg_invalidate"):
            return [mcp_types.TextContent(type="text", text='{"ok": true}')]
        raise ValueError(f"unknown tool: {name}")

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_main())

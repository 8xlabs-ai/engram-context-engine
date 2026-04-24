"""Fake claude-context-ish MCP server. search_code returns seeded chunks."""

from __future__ import annotations

import asyncio
import json
import os

import mcp.types as mcp_types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server


async def _main() -> None:
    seed = os.environ.get("FAKE_CC_CHUNKS", "[]")
    try:
        chunks = json.loads(seed)
    except json.JSONDecodeError:
        chunks = []

    server: Server = Server("fake-cc")

    @server.list_tools()
    async def _list() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name="get_indexing_status",
                description="probe\nUse when checking liveness.",
                inputSchema={"type": "object"},
            ),
            mcp_types.Tool(
                name="search_code",
                description="search\nPrefer this for natural-language code search.",
                inputSchema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                },
            ),
        ]

    @server.call_tool()
    async def _call(name: str, arguments: dict | None) -> list[mcp_types.TextContent]:
        if name == "get_indexing_status":
            return [mcp_types.TextContent(type="text", text='{"status": "completed"}')]
        if name == "search_code":
            return [
                mcp_types.TextContent(
                    type="text", text=json.dumps({"results": chunks})
                )
            ]
        raise ValueError(f"unknown tool: {name}")

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_main())

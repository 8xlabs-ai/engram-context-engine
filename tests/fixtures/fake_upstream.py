"""Fake MCP stdio server used to test Engram's upstream proxy.

Simulates a generic upstream (Serena / MemPalace / claude-context) by exposing
a small toolset whose raw JSON output is deterministic. Name prefix is taken
from argv[1] so the same script can mimic any upstream under test.

Usage (invoked as a subprocess via StdioServerParameters):
    python fake_upstream.py <name_prefix>
"""

from __future__ import annotations

import asyncio
import json
import sys

import mcp.types as mcp_types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server


async def _main(prefix: str) -> None:
    server: Server = Server(f"fake-{prefix}")

    @server.list_tools()
    async def _list_tools() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name=f"{prefix}_hello",
                description=f"{prefix}_hello — echo tool.\nPrefer for tests.",
                inputSchema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": [],
                    "additionalProperties": False,
                },
            ),
            mcp_types.Tool(
                name=f"{prefix}_boom",
                description=f"{prefix}_boom — always fails.\nUse when testing error paths.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
        ]

    @server.call_tool()
    async def _call_tool(
        name: str, arguments: dict | None
    ) -> list[mcp_types.TextContent]:
        if name == f"{prefix}_hello":
            who = (arguments or {}).get("name", "world")
            payload = {"upstream": prefix, "greeting": f"hi {who}"}
            return [mcp_types.TextContent(type="text", text=json.dumps(payload))]
        if name == f"{prefix}_boom":
            raise RuntimeError(f"{prefix}_boom intentionally failed")
        raise ValueError(f"unknown tool: {name}")

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    prefix = sys.argv[1] if len(sys.argv) > 1 else "fake"
    asyncio.run(_main(prefix))

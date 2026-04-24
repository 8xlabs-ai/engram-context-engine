"""Fake Serena-ish MCP server exposing rename_symbol and safe_delete_symbol."""

from __future__ import annotations

import asyncio
import json
import os
import sys

import mcp.types as mcp_types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server


async def _main() -> None:
    fail_on = os.environ.get("FAKE_SERENA_FAIL_ON", "")
    server: Server = Server("fake-serena")

    @server.list_tools()
    async def _list() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name="get_current_config",
                description="probe\nUse when checking liveness.",
                inputSchema={"type": "object"},
            ),
            mcp_types.Tool(
                name="rename_symbol",
                description="rename\nPrefer this for renames.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name_path": {"type": "string"},
                        "relative_path": {"type": "string"},
                        "new_name": {"type": "string"},
                    },
                    "required": ["name_path", "relative_path", "new_name"],
                },
            ),
            mcp_types.Tool(
                name="safe_delete_symbol",
                description="delete\nPrefer this for deletes.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name_path": {"type": "string"},
                        "relative_path": {"type": "string"},
                    },
                    "required": ["name_path", "relative_path"],
                },
            ),
            mcp_types.Tool(
                name="get_symbols_overview",
                description="overview\nUse when listing symbols in a file.",
                inputSchema={
                    "type": "object",
                    "properties": {"relative_path": {"type": "string"}},
                    "required": ["relative_path"],
                },
            ),
        ]

    @server.call_tool()
    async def _call(name: str, arguments: dict | None) -> list[mcp_types.TextContent]:
        if fail_on == name:
            raise RuntimeError(f"fake-serena asked to fail on {name}")
        if name == "get_current_config":
            return [mcp_types.TextContent(type="text", text='{"ok": true}')]
        if name == "rename_symbol":
            return [
                mcp_types.TextContent(
                    type="text", text=json.dumps({"renamed": True, "args": arguments})
                )
            ]
        if name == "safe_delete_symbol":
            return [
                mcp_types.TextContent(
                    type="text", text=json.dumps({"deleted": True, "args": arguments})
                )
            ]
        if name == "get_symbols_overview":
            seed = os.environ.get("FAKE_SERENA_OVERVIEW", "[]")
            return [mcp_types.TextContent(type="text", text=seed)]
        raise ValueError(f"unknown tool: {name}")

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_main())

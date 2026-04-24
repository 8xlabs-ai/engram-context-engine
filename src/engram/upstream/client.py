from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

import mcp.types as mcp_types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

log = logging.getLogger("engram.upstream")


@dataclass
class UpstreamSpec:
    """Per-upstream launch parameters plus presentation metadata."""

    name: str
    command: list[str]
    env: dict[str, str] | None = None
    cwd: str | None = None
    namespace: str = ""  # e.g. "code", "mem", "vec"


class UpstreamConnectionError(RuntimeError):
    pass


@dataclass
class UpstreamClient:
    spec: UpstreamSpec
    session: ClientSession | None = field(default=None, init=False)
    tools: list[mcp_types.Tool] = field(default_factory=list, init=False)
    _stack: AsyncExitStack | None = field(default=None, init=False)

    async def connect(self) -> None:
        self._stack = AsyncExitStack()
        try:
            params = StdioServerParameters(
                command=self.spec.command[0],
                args=list(self.spec.command[1:]),
                env=self.spec.env,
                cwd=self.spec.cwd,
            )
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.session = session
            listing = await session.list_tools()
            self.tools = list(listing.tools)
            log.info(
                "upstream %s connected (%d tools)", self.spec.name, len(self.tools)
            )
        except Exception as exc:
            await self.disconnect()
            raise UpstreamConnectionError(
                f"failed to connect upstream {self.spec.name}: {exc}"
            ) from exc

    async def disconnect(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self.session = None
            self.tools = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> mcp_types.CallToolResult:
        if self.session is None:
            raise UpstreamConnectionError(f"upstream {self.spec.name} not connected")
        return await self.session.call_tool(name, arguments)

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from engram.config import Config
from engram.upstream.client import UpstreamClient, UpstreamSpec

log = logging.getLogger("engram.supervisor")


@dataclass
class Supervisor:
    """Owns the lifecycle of Serena / MemPalace / claude-context MCP clients."""

    specs: list[UpstreamSpec]
    clients: dict[str, UpstreamClient] = field(default_factory=dict)
    _stack: AsyncExitStack | None = field(default=None, init=False)

    async def __aenter__(self) -> "Supervisor":
        self._stack = AsyncExitStack()
        for spec in self.specs:
            client = UpstreamClient(spec)
            try:
                await client.connect()
            except Exception as exc:  # noqa: BLE001
                log.warning("upstream %s unavailable: %s", spec.name, exc)
                continue
            self._stack.push_async_callback(client.disconnect)
            self.clients[spec.name] = client
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None

    def get(self, name: str) -> UpstreamClient | None:
        return self.clients.get(name)


def specs_from_config(config: Config) -> list[UpstreamSpec]:
    u = config.upstreams
    return [
        UpstreamSpec(name="serena", command=list(u.serena.command), namespace="code"),
        UpstreamSpec(name="mempalace", command=list(u.mempalace.command), namespace="mem"),
        UpstreamSpec(
            name="claude_context",
            command=list(u.claude_context.command),
            namespace="vec",
        ),
    ]

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from engram.config import Config
from engram.upstream.client import UpstreamClient, UpstreamConnectionError, UpstreamSpec

log = logging.getLogger("engram.supervisor")


@dataclass
class Supervisor:
    """Owns the lifecycle of Serena / MemPalace / claude-context MCP clients.

    Per-spec connect failures are logged and skipped so a single missing
    upstream does not prevent Engram from booting. Cross-session persistence
    and automatic reconnect are the job of an OS-level supervisor unit
    (see `deploy/units/`), not this in-process helper.

    Post-connect, runs upstream-specific warm-up so the first user-facing
    tool call doesn't pay onboarding latency. Currently: Serena's
    activate_project + check_onboarding_performed.
    """

    specs: list[UpstreamSpec]
    workspace_root: str | None = None
    warm_up: bool = True
    clients: dict[str, UpstreamClient] = field(default_factory=dict)
    _stack: AsyncExitStack | None = field(default=None, init=False)

    async def __aenter__(self) -> "Supervisor":
        self._stack = AsyncExitStack()
        for spec in self.specs:
            client = UpstreamClient(spec)
            try:
                await client.connect()
            except UpstreamConnectionError as exc:
                log.warning("upstream %s unavailable: %s", spec.name, exc)
                continue
            self._stack.push_async_callback(client.disconnect)
            self.clients[spec.name] = client
        if self.warm_up:
            await self._warm_up_serena()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None

    def get(self, name: str) -> UpstreamClient | None:
        return self.clients.get(name)

    async def _warm_up_serena(self) -> None:
        client = self.clients.get("serena")
        if client is None or self.workspace_root is None:
            return
        names = {t.name for t in client.tools}
        if "activate_project" in names:
            try:
                await client.call_tool("activate_project", {"project": self.workspace_root})
                log.info("serena project activated: %s", self.workspace_root)
            except Exception as exc:  # noqa: BLE001
                log.warning("serena activate_project failed: %s", exc)
        if "check_onboarding_performed" in names:
            try:
                result = await client.call_tool("check_onboarding_performed", {})
                if not result.isError and "onboarding" in names:
                    # Onboarding is heavyweight; only trigger if not already done.
                    text = ""
                    for block in result.content or []:
                        text += getattr(block, "text", "") or ""
                    if "false" in text.lower() or "not performed" in text.lower():
                        try:
                            await client.call_tool("onboarding", {})
                            log.info("serena onboarding completed")
                        except Exception as exc:  # noqa: BLE001
                            log.warning("serena onboarding failed: %s", exc)
            except Exception as exc:  # noqa: BLE001
                log.warning("serena check_onboarding_performed failed: %s", exc)


def specs_from_config(config: Config) -> list[UpstreamSpec]:
    import os

    u = config.upstreams
    cc_env = {
        **os.environ,
        "EMBEDDING_PROVIDER": u.claude_context.embedding_provider,
        "EMBEDDING_MODEL": u.claude_context.embedding_model,
        "MILVUS_ADDRESS": u.claude_context.milvus_address,
    }
    if u.claude_context.embedding_provider == "Ollama":
        cc_env["OLLAMA_MODEL"] = u.claude_context.embedding_model
        cc_env.setdefault("OLLAMA_HOST", "http://localhost:11434")
    return [
        UpstreamSpec(name="serena", command=list(u.serena.command), namespace="code"),
        UpstreamSpec(name="mempalace", command=list(u.mempalace.command), namespace="mem"),
        UpstreamSpec(
            name="claude_context",
            command=list(u.claude_context.command),
            namespace="vec",
            env=cc_env,
        ),
    ]

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mcp.types as mcp_types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from engram.config import Config
from engram.events import HookBus
from engram.tools.engram_ns import register_engram_tools
from engram.tools.envelope import failure
from engram.tools.mem_add_anchor import (
    make_mem_add_handler,
)
from engram.tools.proxy import drop_mempalace_prefix, identity, register_proxy, vec_shortener
from engram.tools.registry import ToolRegistry
from engram.tools.vec_enrich import make_vec_search_handler
from engram.tools.write_hooks import make_rename_interceptor, make_safe_delete_interceptor
from engram.upstream.client import UpstreamClient
from engram.upstream.supervisor import Supervisor, specs_from_config
from engram.workers.scheduler import ReconcilerScheduler

log = logging.getLogger("engram.server")

CONFIG_RELPATH = ".engram/config.yaml"


@dataclass(frozen=True)
class ProxyBinding:
    client: UpstreamClient
    namespace: str
    shortener: Any  # Callable[[str], str]
    default_path_tag: str | None
    interceptors: dict[str, Any] | None = None


def build_registry(
    config: Config,
    workspace: Path,
    proxies: list[ProxyBinding] | None = None,
    supervisor: Supervisor | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    anchor_db = workspace / config.anchors.db_path
    register_engram_tools(registry, anchor_db, supervisor=supervisor)
    for binding in proxies or []:
        register_proxy(
            registry=registry,
            client=binding.client,
            namespace=binding.namespace,
            shortener=binding.shortener,
            default_path_tag=binding.default_path_tag,
            interceptors=binding.interceptors,
        )
    return registry


def build_server(registry: ToolRegistry) -> Server:
    server: Server = Server("engram")

    @server.list_tools()
    async def _list_tools() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name=spec.name,
                description=spec.description,
                inputSchema=spec.input_schema,
            )
            for spec in registry.specs()
        ]

    @server.call_tool()
    async def _call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[mcp_types.TextContent]:
        spec = registry.get(name)
        if spec is None:
            payload = failure("invalid-input", f"unknown tool: {name}")
        else:
            try:
                payload = await spec.handler(arguments or {})
            except Exception as exc:  # noqa: BLE001
                log.exception("tool %s raised", name)
                payload = failure("upstream-unavailable", str(exc))
        return [mcp_types.TextContent(type="text", text=json.dumps(payload, sort_keys=True))]

    return server


def resolve_workspace(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    env = os.environ.get("ENGRAM_WORKSPACE")
    if env:
        return Path(env).resolve()
    return Path.cwd().resolve()


def load_config(workspace: Path) -> Config:
    config_path = workspace / CONFIG_RELPATH
    if not config_path.exists():
        raise SystemExit(
            f"engram: no {CONFIG_RELPATH} at {workspace}. Run `engram init` first."
        )
    return Config.load(config_path)


def _bindings_for(
    supervisor: Supervisor,
    anchor_db_path: Path,
    bus: HookBus | None = None,
) -> list[ProxyBinding]:
    bindings: list[ProxyBinding] = []
    serena = supervisor.get("serena")
    if serena is not None:
        interceptors = {
            "rename_symbol": make_rename_interceptor(
                anchor_db_path, serena, lambda: supervisor.get("mempalace"), bus=bus
            ),
            "safe_delete_symbol": make_safe_delete_interceptor(
                anchor_db_path, serena, lambda: supervisor.get("mempalace"), bus=bus
            ),
        }
        bindings.append(ProxyBinding(serena, "code", identity, "B", interceptors))
    mempalace = supervisor.get("mempalace")
    if mempalace is not None:
        mem_interceptors = {
            "mempalace_add_drawer": make_mem_add_handler(anchor_db_path, mempalace),
        }
        bindings.append(
            ProxyBinding(mempalace, "mem", drop_mempalace_prefix, None, mem_interceptors)
        )
    claude_context = supervisor.get("claude_context")
    if claude_context is not None:
        vec_interceptors = {
            "search_code": make_vec_search_handler(
                anchor_db_path, claude_context, lambda: supervisor.get("serena")
            ),
        }
        bindings.append(
            ProxyBinding(claude_context, "vec", vec_shortener, "A", vec_interceptors)
        )
    return bindings


async def _run(workspace: Path, enable_upstreams: bool) -> None:
    config = load_config(workspace)
    specs = specs_from_config(config) if enable_upstreams else []
    bus = HookBus()
    async with Supervisor(specs=specs, workspace_root=str(workspace)) as supervisor:
        registry = build_registry(
            config,
            workspace,
            proxies=_bindings_for(supervisor, workspace / config.anchors.db_path, bus=bus),
            supervisor=supervisor,
        )
        server = build_server(registry)
        log.info(
            "engram mcp starting: %d tools registered (%d upstreams connected)",
            len(registry),
            len(supervisor.clients),
        )
        anchor_db = workspace / config.anchors.db_path
        mempalace_client = supervisor.get("mempalace")

        async def drawer_lookup(drawer_id: str):
            if mempalace_client is None:
                return None
            try:
                r = await mempalace_client.call_tool(
                    "mempalace_get_drawer", {"drawer_id": drawer_id}
                )
            except Exception:  # noqa: BLE001
                return None
            if r.isError:
                return None
            for block in r.content or []:
                txt = getattr(block, "text", None)
                if txt is None:
                    continue
                try:
                    return json.loads(txt)
                except json.JSONDecodeError:
                    continue
            return None

        scheduler = ReconcilerScheduler(
            db_path=anchor_db,
            drawer_lookup=drawer_lookup,
            interval_hours=float(config.anchors.reconcile_interval_hours),
        )
        scheduler.start()
        try:
            async with stdio_server() as (read_stream, write_stream):
                await server.run(
                    read_stream, write_stream, server.create_initialization_options()
                )
        finally:
            await scheduler.stop()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    workspace = resolve_workspace(os.environ.get("ENGRAM_WORKSPACE"))
    enable_upstreams = os.environ.get("ENGRAM_DISABLE_UPSTREAMS") != "1"
    try:
        asyncio.run(_run(workspace, enable_upstreams))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

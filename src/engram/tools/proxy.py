from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import mcp.types as mcp_types

from engram.tools.envelope import failure, latency_meter, success
from engram.tools.registry import ToolRegistry, ToolSpec
from engram.upstream.client import UpstreamClient

log = logging.getLogger("engram.proxy")

NameShortener = Callable[[str], str]

MEM_PREFIX = "mempalace_"

# Per doc 07 §4 the user-facing surface uses CRUD-shortened names rather than
# raw drawer/_drawers suffixes. Map upstream → user-facing.
MEM_ALIASES: dict[str, str] = {
    "mempalace_add_drawer": "add",
    "mempalace_get_drawer": "get",
    "mempalace_delete_drawer": "delete",
    "mempalace_update_drawer": "update",
    "mempalace_list_drawers": "list",
}


def drop_mempalace_prefix(name: str) -> str:
    if name in MEM_ALIASES:
        return MEM_ALIASES[name]
    return name[len(MEM_PREFIX):] if name.startswith(MEM_PREFIX) else name


# Per doc 07 §4: vec.* uses verb-shortened names, not the raw upstream names.
VEC_ALIASES: dict[str, str] = {
    "index_codebase": "index",
    "search_code": "search",
    "clear_index": "clear",
    "get_indexing_status": "status",
}


def vec_shortener(name: str) -> str:
    return VEC_ALIASES.get(name, name)


def identity(name: str) -> str:
    return name


def register_proxy(
    registry: ToolRegistry,
    client: UpstreamClient,
    namespace: str,
    shortener: NameShortener = identity,
    default_path_tag: str | None = None,
    interceptors: dict[str, Any] | None = None,
) -> int:
    """Register every tool on `client` under `namespace.<shortened_name>`.

    `interceptors` is an optional mapping of *upstream* tool name → a
    pre-constructed ToolHandler that replaces the generic proxy handler.
    Used to attach the Link-Layer rename / safe-delete write paths.

    Returns the number of tools registered.
    """
    interceptors = interceptors or {}
    registered = 0
    for tool in client.tools:
        short_name = shortener(tool.name)
        fq_name = f"{namespace}.{short_name}"
        handler = interceptors.get(tool.name) or _make_handler(
            client=client,
            upstream_name=tool.name,
            proxy_name=fq_name,
            upstream_label=client.spec.name,
            default_path_tag=default_path_tag,
        )
        description = tool.description or f"{fq_name} (proxy of {client.spec.name}:{tool.name})"
        registry.register(
            ToolSpec(
                name=fq_name,
                description=description,
                input_schema=tool.inputSchema or {"type": "object"},
                handler=handler,
            )
        )
        registered += 1
    log.info("registered %d %s.* tools from upstream %s", registered, namespace, client.spec.name)
    return registered


def _make_handler(
    client: UpstreamClient,
    upstream_name: str,
    proxy_name: str,
    upstream_label: str,
    default_path_tag: str | None,
) -> Any:
    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            try:
                result = await client.call_tool(upstream_name, arguments)
            except Exception as exc:  # noqa: BLE001
                log.exception("upstream call failed: %s", proxy_name)
                return failure(
                    "upstream-unavailable",
                    f"{upstream_label}:{upstream_name} failed: {exc}",
                    meta_extra={"upstream": upstream_label, "latency_ms": m["latency_ms"]},
                )

        if result.isError:
            return failure(
                "upstream-unavailable",
                f"{upstream_label}:{upstream_name} returned error",
                details=_result_as_plain(result),
                meta_extra={
                    "upstream": upstream_label,
                    "latency_ms": m["latency_ms"],
                },
            )

        meta_extra: dict[str, Any] = {
            "upstream": upstream_label,
            "latency_ms": m["latency_ms"],
        }
        if default_path_tag is not None:
            meta_extra["path_used"] = default_path_tag
        return success(_result_as_plain(result), meta_extra=meta_extra)

    return handler


def _result_as_plain(result: mcp_types.CallToolResult) -> Any:
    """Convert CallToolResult into a JSON-friendly value.

    Preserves structuredContent when present, else flattens text content.
    """
    if result.structuredContent is not None:
        return result.structuredContent
    texts: list[Any] = []
    for block in result.content:
        if isinstance(block, mcp_types.TextContent):
            try:
                texts.append(json.loads(block.text))
            except json.JSONDecodeError:
                texts.append(block.text)
    if not texts:
        return None
    if len(texts) == 1:
        return texts[0]
    return texts

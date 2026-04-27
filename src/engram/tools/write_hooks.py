"""Write-path interceptors for code.* tools.

Shape-A (MCP-client orchestrator) means every Serena rename/delete is first
routed through Engram. These interceptors open a SQLite transaction before
forwarding to Serena and commit only on upstream success — the contract in
docs 05 §4.1 and the `mcp-proxy` spec.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from engram.events import (
    EVENT_FILE_REPLACED,
    EVENT_SYMBOL_RENAMED,
    EVENT_SYMBOL_TOMBSTONED,
    HookBus,
)
from engram.link.store import (
    get_symbol,
    open_db,
    rename_symbol,
    tombstone_symbol,
    upsert_symbol,
)
from engram.tools.envelope import failure, latency_meter, success
from engram.tools.registry import ToolHandler
from engram.upstream.client import UpstreamClient

log = logging.getLogger("engram.write_hooks")

ClientGetter = Callable[[], UpstreamClient | None]


def make_rename_interceptor(
    db_path: Path,
    serena_client: UpstreamClient,
    kg_client_getter: ClientGetter,
    bus: HookBus | None = None,
) -> ToolHandler:
    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            name_path = arguments.get("name_path")
            relative_path = arguments.get("relative_path")
            new_name = arguments.get("new_name")
            if not all(isinstance(x, str) and x for x in (name_path, relative_path, new_name)):
                return failure(
                    "invalid-input",
                    "name_path, relative_path, and new_name are required",
                    meta_extra={"latency_ms": m["latency_ms"], "upstream": "serena"},
                )

            conn = open_db(db_path)
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = get_symbol(conn, name_path, relative_path)
                if existing is None:
                    symbol_id = upsert_symbol(
                        conn, name_path=name_path, relative_path=relative_path, kind=0
                    )
                else:
                    symbol_id = existing.symbol_id
                rename_symbol(conn, symbol_id, new_name_path=_rename_preview(name_path, new_name))

                try:
                    result = await serena_client.call_tool("rename_symbol", arguments)
                except Exception as exc:  # noqa: BLE001
                    conn.execute("ROLLBACK")
                    return failure(
                        "consistency-state-hint",
                        f"serena rename failed; rolled back: {exc}",
                        details={"symbol_id": symbol_id},
                        meta_extra={"latency_ms": m["latency_ms"], "upstream": "serena"},
                    )
                if result.isError:
                    conn.execute("ROLLBACK")
                    return failure(
                        "consistency-state-hint",
                        "serena rename returned error; rolled back",
                        details={"symbol_id": symbol_id},
                        meta_extra={"latency_ms": m["latency_ms"], "upstream": "serena"},
                    )
                conn.execute("COMMIT")
            finally:
                conn.close()

        new_name_path = _rename_preview(name_path, new_name)
        await _record_rename_in_kg(
            kg_client_getter(),
            old_name_path=name_path,
            new_name_path=new_name_path,
        )
        if bus is not None:
            await bus.publish(
                EVENT_SYMBOL_RENAMED,
                {
                    "symbol_id": symbol_id,
                    "old_name_path": name_path,
                    "new_name_path": new_name_path,
                    "relative_path": relative_path,
                },
            )
        return success(
            {"symbol_id": symbol_id, "upstream": _structured(result)},
            meta_extra={
                "latency_ms": m["latency_ms"],
                "upstream": "serena",
                "path_used": "B",
            },
        )

    return handler


def make_safe_delete_interceptor(
    db_path: Path,
    serena_client: UpstreamClient,
    kg_client_getter: ClientGetter,
    bus: HookBus | None = None,
) -> ToolHandler:
    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            name_path = arguments.get("name_path")
            relative_path = arguments.get("relative_path")
            if not all(isinstance(x, str) and x for x in (name_path, relative_path)):
                return failure(
                    "invalid-input",
                    "name_path and relative_path are required",
                    meta_extra={"latency_ms": m["latency_ms"], "upstream": "serena"},
                )
            conn = open_db(db_path)
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = get_symbol(conn, name_path, relative_path)
                try:
                    result = await serena_client.call_tool("safe_delete_symbol", arguments)
                except Exception as exc:  # noqa: BLE001
                    conn.execute("ROLLBACK")
                    return failure(
                        "consistency-state-hint",
                        f"serena safe_delete failed; rolled back: {exc}",
                        meta_extra={"latency_ms": m["latency_ms"], "upstream": "serena"},
                    )
                if result.isError:
                    conn.execute("ROLLBACK")
                    return failure(
                        "consistency-state-hint",
                        "serena safe_delete returned error; rolled back",
                        meta_extra={"latency_ms": m["latency_ms"], "upstream": "serena"},
                    )
                if existing is not None:
                    tombstone_symbol(conn, existing.symbol_id)
                conn.execute("COMMIT")
            finally:
                conn.close()

        if existing is not None:
            await _invalidate_in_kg(kg_client_getter(), name_path=name_path)
        if bus is not None and existing is not None:
            await bus.publish(
                EVENT_SYMBOL_TOMBSTONED,
                {
                    "symbol_id": existing.symbol_id,
                    "name_path": name_path,
                    "relative_path": relative_path,
                },
            )
        return success(
            {"upstream": _structured(result)},
            meta_extra={
                "latency_ms": m["latency_ms"],
                "upstream": "serena",
                "path_used": "B",
            },
        )

    return handler


def make_file_edit_interceptor(
    serena_client: UpstreamClient,
    upstream_tool: str,
    *,
    bus: HookBus | None = None,
) -> ToolHandler:
    """Forward a Serena file-edit tool, then emit `file.replaced` on success.

    Used for `replace_symbol_body`, `insert_after_symbol`, `insert_before_symbol`,
    `replace_content`, `insert_at_line`, `delete_lines`, `replace_lines`, and
    `create_text_file`. Closes original task 2.7.

    The interceptor does not open a SQLite tx — these tools mutate file content
    only, not the symbol-identity table. Anchor cache eviction happens via the
    bus subscriber on `EVENT_FILE_REPLACED`.
    """

    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            relative_path = arguments.get("relative_path")
            try:
                result = await serena_client.call_tool(upstream_tool, arguments)
            except Exception as exc:  # noqa: BLE001
                return failure(
                    "upstream-unavailable",
                    f"serena {upstream_tool} failed: {exc}",
                    meta_extra={"latency_ms": m["latency_ms"], "upstream": "serena"},
                )
            if result.isError:
                return failure(
                    "upstream-unavailable",
                    f"serena {upstream_tool} returned error",
                    details=_structured(result),
                    meta_extra={"latency_ms": m["latency_ms"], "upstream": "serena"},
                )

        if bus is not None and isinstance(relative_path, str) and relative_path:
            await bus.publish(
                EVENT_FILE_REPLACED,
                {
                    "relative_path": relative_path,
                    "change_type": "edit",
                    "source": "engram_write_hook",
                    "tool": upstream_tool,
                    "agent": "engram",
                    "ts": time.time(),
                },
            )
        return success(
            _structured(result),
            meta_extra={
                "latency_ms": m["latency_ms"],
                "upstream": "serena",
                "path_used": "B",
            },
        )

    return handler


# ---------------------------------------------------------------------------
# KG helpers
# ---------------------------------------------------------------------------


async def _record_rename_in_kg(
    client: UpstreamClient | None,
    *,
    old_name_path: str,
    new_name_path: str,
) -> None:
    if client is None or old_name_path == new_name_path:
        return
    try:
        await client.call_tool(
            "mempalace_kg_add",
            {
                "subject": old_name_path,
                "predicate": "renamed_to",
                "object": new_name_path,
            },
        )
        await client.call_tool(
            "mempalace_kg_invalidate",
            {"subject": old_name_path, "predicate": "is"},
        )
    except Exception:
        log.exception("failed to record rename in KG; ignoring")


async def _invalidate_in_kg(client: UpstreamClient | None, *, name_path: str) -> None:
    if client is None:
        return
    try:
        await client.call_tool(
            "mempalace_kg_invalidate",
            {"subject": name_path, "predicate": "is"},
        )
    except Exception:
        log.exception("failed to invalidate KG entity; ignoring")


# ---------------------------------------------------------------------------
# misc
# ---------------------------------------------------------------------------


def _rename_preview(old_name_path: str, new_name: str) -> str:
    """Compute the post-rename name_path using Serena's convention.

    Serena uses `/`-delimited name_paths. Rename swaps the last segment.
    """
    if "/" not in old_name_path:
        return new_name
    parent, _ = old_name_path.rsplit("/", 1)
    return f"{parent}/{new_name}"


def _structured(result: Any) -> Any:
    if getattr(result, "structuredContent", None):
        return dict(result.structuredContent)
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is None:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return None

"""In-process pub/sub bus for Link Layer events.

Producers (write_hooks, mem_add_anchor, vec_enrich, proxy interceptors)
publish events; consumers (LRUCache invalidator, future feature modules)
subscribe. At-least-once delivery with idempotent handlers.

This is the M2-3.7 dependency that 2.7 and 3.7 both wait on. Keep it
boring: a list of (event_type, async handler) tuples and a publish() that
fans out. No threads, no cross-process — everything runs in the asyncio
loop that owns the MCP server.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("engram.events")

# Event types — keep this small + stable. Adding new types is non-breaking;
# renaming or removing them is breaking. See doc 05 §6 for the contract.
EVENT_SYMBOL_RENAMED = "symbol.renamed"
EVENT_SYMBOL_TOMBSTONED = "symbol.tombstoned"
EVENT_FILE_REPLACED = "file.replaced"
EVENT_MEMORY_WRITTEN = "memory.written"
EVENT_MEMORY_DELETED = "memory.deleted"

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class HookBus:
    handlers: dict[str, list[EventHandler]] = field(default_factory=dict)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self.handlers.setdefault(event_type, []).append(handler)

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        targets = list(self.handlers.get(event_type, []))
        if not targets:
            return
        results = await asyncio.gather(
            *(_safe_invoke(h, event_type, payload) for h in targets),
            return_exceptions=False,
        )
        del results  # we log failures inline; nothing to return


async def _safe_invoke(
    handler: EventHandler, event_type: str, payload: dict[str, Any]
) -> None:
    try:
        await handler(payload)
    except Exception:
        log.exception("hook handler raised on %s", event_type)

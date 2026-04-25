"""LRU cache for router responses.

Keyed on (tool_name, canonicalized_args). Canonicalization = json.dumps with
sort_keys=True so dict order doesn't spuriously miss. Bounded to
`max_entries` (default 1024).
"""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from engram.events import (
    EVENT_FILE_REPLACED,
    EVENT_SYMBOL_RENAMED,
    EVENT_SYMBOL_TOMBSTONED,
    HookBus,
)

DEFAULT_MAX_ENTRIES = 1024


def canonicalize(args: dict[str, Any]) -> str:
    return json.dumps(args, sort_keys=True, default=str)


@dataclass
class LRUCache:
    max_entries: int = DEFAULT_MAX_ENTRIES
    _store: OrderedDict[tuple[str, str], Any] = field(default_factory=OrderedDict)

    def get(self, tool_name: str, args: dict[str, Any]) -> Any | None:
        key = (tool_name, canonicalize(args))
        if key not in self._store:
            return None
        self._store.move_to_end(key)
        return self._store[key]

    def put(self, tool_name: str, args: dict[str, Any], value: Any) -> None:
        key = (tool_name, canonicalize(args))
        if key in self._store:
            self._store.move_to_end(key)
            self._store[key] = value
            return
        self._store[key] = value
        while len(self._store) > self.max_entries:
            self._store.popitem(last=False)

    def invalidate_if(self, predicate) -> int:
        """Remove every entry whose (tool_name, args_json) matches predicate.

        Used by Link Layer events to evict stale cache rows on rename/delete/move.
        """
        to_remove = [
            key for key in self._store if predicate(*key)
        ]
        for key in to_remove:
            del self._store[key]
        return len(to_remove)

    def clear(self) -> None:
        self._store.clear()

    def subscribe_to(self, bus: HookBus) -> None:
        """Wire LRU eviction to Link Layer events.

        - `symbol.renamed`: drop entries whose key references the old name_path.
        - `symbol.tombstoned`: drop entries referencing the symbol's name_path.
        - `file.replaced`: drop entries referencing the relative_path.
        """

        async def on_renamed(payload: Any) -> None:
            old = str(payload.get("old_name_path") or "")
            new = str(payload.get("new_name_path") or "")
            self.invalidate_if(
                lambda _tool, args: (old and old in args) or (new and new in args)
            )

        async def on_tombstoned(payload: Any) -> None:
            name_path = str(payload.get("name_path") or "")
            self.invalidate_if(lambda _t, args: bool(name_path) and name_path in args)

        async def on_file_replaced(payload: Any) -> None:
            rel = str(payload.get("relative_path") or "")
            self.invalidate_if(lambda _t, args: bool(rel) and rel in args)

        bus.subscribe(EVENT_SYMBOL_RENAMED, on_renamed)
        bus.subscribe(EVENT_SYMBOL_TOMBSTONED, on_tombstoned)
        bus.subscribe(EVENT_FILE_REPLACED, on_file_replaced)

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, key: tuple[str, str]) -> bool:
        return key in self._store

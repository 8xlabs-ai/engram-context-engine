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

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, key: tuple[str, str]) -> bool:
        return key in self._store

from __future__ import annotations

import asyncio

from engram.events import (
    EVENT_FILE_REPLACED,
    EVENT_SYMBOL_RENAMED,
    EVENT_SYMBOL_TOMBSTONED,
    HookBus,
)
from engram.router.cache import LRUCache


def test_bus_publishes_to_all_handlers() -> None:
    bus = HookBus()
    captured: list[dict] = []

    async def h1(p):
        captured.append({"h": 1, **p})

    async def h2(p):
        captured.append({"h": 2, **p})

    bus.subscribe("x", h1)
    bus.subscribe("x", h2)
    asyncio.run(bus.publish("x", {"k": 1}))
    assert {c["h"] for c in captured} == {1, 2}


def test_bus_isolates_handler_failure() -> None:
    bus = HookBus()
    captured: list[dict] = []

    async def boom(_p):
        raise RuntimeError("nope")

    async def good(p):
        captured.append(p)

    bus.subscribe("x", boom)
    bus.subscribe("x", good)
    asyncio.run(bus.publish("x", {"v": 7}))
    assert captured == [{"v": 7}]


def test_cache_evicts_on_symbol_renamed() -> None:
    bus = HookBus()
    cache = LRUCache(max_entries=8)
    cache.subscribe_to(bus)

    cache.put("engram.why", {"name_path": "Foo/process"}, "old-result")
    cache.put("engram.why", {"name_path": "Bar/run"}, "kept")

    asyncio.run(
        bus.publish(
            EVENT_SYMBOL_RENAMED,
            {"old_name_path": "Foo/process", "new_name_path": "Foo/run"},
        )
    )

    assert cache.get("engram.why", {"name_path": "Foo/process"}) is None
    assert cache.get("engram.why", {"name_path": "Bar/run"}) == "kept"


def test_cache_evicts_on_symbol_tombstoned() -> None:
    bus = HookBus()
    cache = LRUCache()
    cache.subscribe_to(bus)
    cache.put("engram.why", {"name_path": "Foo/process"}, "v")
    asyncio.run(
        bus.publish(EVENT_SYMBOL_TOMBSTONED, {"name_path": "Foo/process"})
    )
    assert cache.get("engram.why", {"name_path": "Foo/process"}) is None


def test_cache_evicts_on_file_replaced() -> None:
    bus = HookBus()
    cache = LRUCache()
    cache.subscribe_to(bus)
    cache.put("vec.search", {"path": "src/foo.py"}, "v")
    cache.put("vec.search", {"path": "src/bar.py"}, "kept")
    asyncio.run(bus.publish(EVENT_FILE_REPLACED, {"relative_path": "src/foo.py"}))
    assert cache.get("vec.search", {"path": "src/foo.py"}) is None
    assert cache.get("vec.search", {"path": "src/bar.py"}) == "kept"

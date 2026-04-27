from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from engram.events import EVENT_FILE_REPLACED, HookBus
from engram.tools.write_hooks import make_file_edit_interceptor
from engram.upstream.client import UpstreamSpec
from engram.upstream.supervisor import Supervisor

REPO_SRC = Path(__file__).parent.parent.parent / "src"
FIX = Path(__file__).parent.parent / "fixtures"


def _serena_spec(extra_env: dict | None = None) -> UpstreamSpec:
    env = {**os.environ, "PYTHONPATH": str(REPO_SRC)}
    if extra_env:
        env.update(extra_env)
    return UpstreamSpec(
        name="serena",
        command=[sys.executable, str(FIX / "fake_serena.py")],
        env=env,
        namespace="code",
    )


def test_file_edit_emits_file_replaced_event(tmp_path: Path) -> None:
    received: list[dict] = []

    async def capture(payload):
        received.append(payload)

    async def run() -> None:
        async with Supervisor(specs=[_serena_spec()]) as sup:
            serena = sup.get("serena")
            assert serena is not None
            bus = HookBus()
            bus.subscribe(EVENT_FILE_REPLACED, capture)
            handler = make_file_edit_interceptor(serena, "replace_symbol_body", bus=bus)
            resp = await handler({"name_path": "Foo", "relative_path": "src/foo.py", "body": "..."})
            assert "result" in resp
            assert resp["meta"]["upstream"] == "serena"

    asyncio.run(run())
    assert len(received) == 1
    assert received[0]["relative_path"] == "src/foo.py"
    assert received[0]["tool"] == "replace_symbol_body"
    assert received[0]["change_type"] == "edit"
    assert received[0]["source"] == "engram_write_hook"
    assert received[0]["agent"] == "engram"
    assert isinstance(received[0]["ts"], float)


def test_file_edit_failure_does_not_emit_event(tmp_path: Path) -> None:
    received: list[dict] = []

    async def capture(payload):
        received.append(payload)

    async def run() -> dict:
        async with Supervisor(
            specs=[_serena_spec({"FAKE_SERENA_FAIL_ON": "create_text_file"})]
        ) as sup:
            serena = sup.get("serena")
            bus = HookBus()
            bus.subscribe(EVENT_FILE_REPLACED, capture)
            handler = make_file_edit_interceptor(serena, "create_text_file", bus=bus)
            return await handler({"relative_path": "src/new.py", "content": "x"})

    resp = asyncio.run(run())
    assert resp["error"]["code"] == "upstream-unavailable"
    assert received == []


def test_file_edit_invalidates_cache_via_bus(tmp_path: Path) -> None:
    """Integration: cache subscribed to bus + file edit tool emits event."""
    from engram.router.cache import LRUCache

    cache = LRUCache()
    bus = HookBus()
    cache.subscribe_to(bus)
    cache.put("vec.search", {"path": "src/foo.py"}, "stale")
    cache.put("vec.search", {"path": "src/bar.py"}, "kept")

    async def run() -> None:
        async with Supervisor(specs=[_serena_spec()]) as sup:
            serena = sup.get("serena")
            handler = make_file_edit_interceptor(serena, "replace_symbol_body", bus=bus)
            await handler({"relative_path": "src/foo.py", "name_path": "Foo", "body": "..."})

    asyncio.run(run())
    assert cache.get("vec.search", {"path": "src/foo.py"}) is None
    assert cache.get("vec.search", {"path": "src/bar.py"}) == "kept"

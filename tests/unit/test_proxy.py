from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from engram.tools.proxy import drop_mempalace_prefix, register_proxy
from engram.tools.registry import ToolRegistry
from engram.upstream.client import UpstreamClient, UpstreamSpec
from engram.upstream.supervisor import Supervisor

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_upstream.py"


def _spec(name: str, namespace: str, prefix: str) -> UpstreamSpec:
    return UpstreamSpec(
        name=name,
        command=[sys.executable, str(FAKE), prefix],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parent.parent.parent / "src")},
        namespace=namespace,
    )


def test_drop_mempalace_prefix() -> None:
    assert drop_mempalace_prefix("mempalace_add_drawer") == "add_drawer"
    assert drop_mempalace_prefix("no_prefix") == "no_prefix"


def test_connect_and_list_tools() -> None:
    async def run() -> None:
        client = UpstreamClient(_spec("fake", "code", "fake"))
        await client.connect()
        try:
            names = {t.name for t in client.tools}
            assert names == {"fake_hello", "fake_boom"}
        finally:
            await client.disconnect()

    asyncio.run(run())


def test_register_proxy_namespaces_tools() -> None:
    async def run() -> None:
        client = UpstreamClient(_spec("fake", "code", "srn"))
        await client.connect()
        try:
            registry = ToolRegistry()
            count = register_proxy(registry, client, namespace="code", default_path_tag="B")
            assert count == 2
            assert "code.srn_hello" in registry
            assert "code.srn_boom" in registry
            spec = registry.get("code.srn_hello")
            payload = await spec.handler({"name": "engram"})  # type: ignore[union-attr]
            assert payload["result"]["greeting"] == "hi engram"
            assert payload["meta"]["upstream"] == "fake"
            assert payload["meta"]["path_used"] == "B"
        finally:
            await client.disconnect()

    asyncio.run(run())


def test_proxy_maps_upstream_error_to_failure_envelope() -> None:
    async def run() -> None:
        client = UpstreamClient(_spec("fake", "code", "boom"))
        await client.connect()
        try:
            registry = ToolRegistry()
            register_proxy(registry, client, namespace="code")
            spec = registry.get("code.boom_boom")
            payload = await spec.handler({})  # type: ignore[union-attr]
            assert "error" in payload
            assert payload["error"]["code"] == "upstream-unavailable"
        finally:
            await client.disconnect()

    asyncio.run(run())


def test_supervisor_connects_multiple_upstreams() -> None:
    async def run() -> None:
        specs = [
            _spec("fake_code", "code", "code"),
            _spec("fake_mem", "mem", "mempalace_ext"),
            _spec("fake_vec", "vec", "vec"),
        ]
        async with Supervisor(specs=specs) as sup:
            assert set(sup.clients) == {"fake_code", "fake_mem", "fake_vec"}

    asyncio.run(run())


def test_supervisor_skips_dead_upstream_without_failing() -> None:
    async def run() -> None:
        specs = [
            _spec("alive", "code", "alive"),
            UpstreamSpec(
                name="dead",
                command=[sys.executable, "-c", "import sys; sys.exit(7)"],
                namespace="mem",
            ),
        ]
        async with Supervisor(specs=specs) as sup:
            assert "alive" in sup.clients
            assert "dead" not in sup.clients

    asyncio.run(run())

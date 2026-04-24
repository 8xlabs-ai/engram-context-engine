from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from engram.cli import main as cli_main
from engram.config import Config
from engram.link.store import init_db
from engram.server import build_registry, build_server


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    runner = CliRunner()
    result = runner.invoke(
        cli_main,
        [
            "init",
            "--workspace",
            str(tmp_path),
            "--embedding-provider",
            "Ollama",
            "--skip-prereq-check",
        ],
    )
    assert result.exit_code == 0, result.output
    return tmp_path


def test_registry_contains_engram_health(workspace: Path) -> None:
    cfg = Config.load(workspace / ".engram/config.yaml")
    registry = build_registry(cfg, workspace)
    assert "engram.health" in registry


def test_engram_health_returns_success_envelope(workspace: Path) -> None:
    import asyncio

    cfg = Config.load(workspace / ".engram/config.yaml")
    registry = build_registry(cfg, workspace)
    spec = registry.get("engram.health")
    assert spec is not None
    payload = asyncio.run(spec.handler({}))
    assert "result" in payload
    assert payload["meta"]["protocol_version"] == "v1"
    # No supervisor attached in this test → all upstreams unreachable.
    assert payload["result"]["status"] == "down"
    assert payload["result"]["anchor_store"]["symbols"] == 0
    assert set(payload["result"]["upstreams"]) == {"serena", "mempalace", "claude_context"}


def test_engram_health_reports_anchor_counts(workspace: Path) -> None:
    import asyncio

    db = workspace / ".engram/anchors.sqlite"
    conn = init_db(db)
    conn.execute(
        "INSERT INTO symbols (name_path, relative_path, kind) VALUES (?, ?, ?)",
        ("Foo/process", "src/foo.py", 12),
    )
    conn.close()

    cfg = Config.load(workspace / ".engram/config.yaml")
    registry = build_registry(cfg, workspace)
    spec = registry.get("engram.health")
    assert spec is not None
    payload = asyncio.run(spec.handler({}))
    assert payload["result"]["anchor_store"]["symbols"] == 1


def test_build_server_wires_registry(workspace: Path) -> None:
    cfg = Config.load(workspace / ".engram/config.yaml")
    registry = build_registry(cfg, workspace)
    server = build_server(registry)
    assert server.name == "engram"


def test_call_tool_round_trip(workspace: Path) -> None:
    import asyncio

    cfg = Config.load(workspace / ".engram/config.yaml")
    registry = build_registry(cfg, workspace)
    server = build_server(registry)
    handler = server.request_handlers

    call_tool_type = next(
        k for k in handler if k.__name__ == "CallToolRequest"
    )
    list_tools_type = next(
        k for k in handler if k.__name__ == "ListToolsRequest"
    )

    list_req = list_tools_type(method="tools/list", params=None)
    list_result = asyncio.run(handler[list_tools_type](list_req))
    tool_names = {t.name for t in list_result.root.tools}
    assert "engram.health" in tool_names

    call_req = call_tool_type(
        method="tools/call",
        params={"name": "engram.health", "arguments": {}},
    )
    call_result = asyncio.run(handler[call_tool_type](call_req))
    text_block = call_result.root.content[0]
    payload = json.loads(text_block.text)
    # No supervisor wired in this synchronous build → down.
    assert payload["result"]["status"] in {"ok", "degraded", "down"}
    assert payload["meta"]["protocol_version"] == "v1"

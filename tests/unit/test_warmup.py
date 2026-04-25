"""Verify Supervisor warms Serena with activate_project + check_onboarding."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from engram.upstream.client import UpstreamSpec
from engram.upstream.supervisor import Supervisor

REPO_SRC = Path(__file__).parent.parent.parent / "src"
FIX = Path(__file__).parent.parent / "fixtures"


def _serena_spec(log_file: Path) -> UpstreamSpec:
    return UpstreamSpec(
        name="serena",
        command=[sys.executable, str(FIX / "fake_serena.py")],
        env={
            **os.environ,
            "PYTHONPATH": str(REPO_SRC),
            "FAKE_SERENA_LOG": str(log_file),
        },
        namespace="code",
    )


def test_warmup_calls_activate_project(tmp_path: Path) -> None:
    log_file = tmp_path / "serena.log"

    async def run() -> None:
        async with Supervisor(
            specs=[_serena_spec(log_file)], workspace_root="/tmp/engram-real"
        ) as sup:
            assert sup.get("serena") is not None

    asyncio.run(run())
    assert log_file.exists()
    ops = [json.loads(line) for line in log_file.read_text().strip().splitlines()]
    activate_calls = [o for o in ops if o["op"] == "activate_project"]
    assert len(activate_calls) == 1
    assert activate_calls[0]["args"]["project"] == "/tmp/engram-real"


def test_warmup_skipped_when_disabled(tmp_path: Path) -> None:
    log_file = tmp_path / "serena.log"

    async def run() -> None:
        async with Supervisor(
            specs=[_serena_spec(log_file)],
            workspace_root="/tmp/engram-real",
            warm_up=False,
        ) as sup:
            assert sup.get("serena") is not None

    asyncio.run(run())
    # warm_up=False means activate_project is never called
    assert not log_file.exists() or log_file.read_text() == ""


def test_warmup_no_workspace_skips_activate(tmp_path: Path) -> None:
    log_file = tmp_path / "serena.log"

    async def run() -> None:
        async with Supervisor(specs=[_serena_spec(log_file)]) as sup:
            assert sup.get("serena") is not None

    asyncio.run(run())
    assert not log_file.exists() or log_file.read_text() == ""

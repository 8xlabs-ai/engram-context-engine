from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import patch

from engram.tools.contradicts import _call_subprocess, register_contradicts
from engram.tools.registry import ToolRegistry


def test_contradicts_happy_path_via_injected_checker(tmp_path: Path) -> None:
    async def fake_check(text, extras):
        return [{"type": "entity_confusion", "text": text}]

    reg = ToolRegistry()
    register_contradicts(reg, check=fake_check)
    tool = reg.get("engram.contradicts")
    resp = asyncio.run(tool.handler({"text": "Alice wrote code; Alise shipped it."}))  # type: ignore[union-attr]
    assert resp["result"]["issues"][0]["type"] == "entity_confusion"


def test_contradicts_returns_fact_checker_unavailable() -> None:
    async def fake_check(text, extras):
        return None

    reg = ToolRegistry()
    register_contradicts(reg, check=fake_check)
    tool = reg.get("engram.contradicts")
    resp = asyncio.run(tool.handler({"text": "hello"}))  # type: ignore[union-attr]
    assert resp["error"]["code"] == "fact-checker-unavailable"


def test_contradicts_invalid_input() -> None:
    async def fake_check(text, extras):
        return []

    reg = ToolRegistry()
    register_contradicts(reg, check=fake_check)
    tool = reg.get("engram.contradicts")
    resp = asyncio.run(tool.handler({"text": ""}))  # type: ignore[union-attr]
    assert resp["error"]["code"] == "invalid-input"


def test_contradicts_propagates_raise_as_unavailable() -> None:
    async def fake_check(text, extras):
        raise RuntimeError("boom")

    reg = ToolRegistry()
    register_contradicts(reg, check=fake_check)
    tool = reg.get("engram.contradicts")
    resp = asyncio.run(tool.handler({"text": "x"}))  # type: ignore[union-attr]
    assert resp["error"]["code"] == "fact-checker-unavailable"


def _completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["python"], returncode=returncode, stdout=stdout, stderr=""
    )


def test_subprocess_exit_zero_means_no_contradictions() -> None:
    with patch("engram.tools.contradicts.subprocess.run") as run:
        run.return_value = _completed(0, "No contradictions found.\n")
        result = asyncio.run(_call_subprocess("text", {}))
    assert result == []


def test_subprocess_exit_one_parses_json_issues() -> None:
    payload = '[{"type": "kg_contradiction", "evidence": "x"}]'
    with patch("engram.tools.contradicts.subprocess.run") as run:
        run.return_value = _completed(1, payload)
        result = asyncio.run(_call_subprocess("text", {}))
    assert result == [{"type": "kg_contradiction", "evidence": "x"}]


def test_subprocess_exit_one_with_bad_stdout_returns_none() -> None:
    with patch("engram.tools.contradicts.subprocess.run") as run:
        run.return_value = _completed(1, "not json")
        result = asyncio.run(_call_subprocess("text", {}))
    assert result is None


def test_subprocess_passes_palace_path_when_supplied() -> None:
    with patch("engram.tools.contradicts.subprocess.run") as run:
        run.return_value = _completed(0, "No contradictions found.\n")
        asyncio.run(_call_subprocess("text", {"palace_path": "/tmp/p"}))
    cmd = run.call_args.args[0]
    assert "--palace" in cmd and "/tmp/p" in cmd
    assert "--stdin" in cmd
    assert run.call_args.kwargs["input"] == "text"


def test_contradicts_description_passes_lint() -> None:
    from engram.tools.lint import lint_engram_namespace

    reg = ToolRegistry()
    register_contradicts(reg)
    issues = lint_engram_namespace(reg)
    assert issues == [], "\n".join(issues)

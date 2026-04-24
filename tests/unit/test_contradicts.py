from __future__ import annotations

import asyncio
from pathlib import Path

from engram.tools.contradicts import register_contradicts
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


def test_contradicts_description_passes_lint() -> None:
    from engram.tools.lint import lint_engram_namespace

    reg = ToolRegistry()
    register_contradicts(reg)
    issues = lint_engram_namespace(reg)
    assert issues == [], "\n".join(issues)

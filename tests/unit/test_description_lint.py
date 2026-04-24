from __future__ import annotations

from pathlib import Path

import pytest

from engram.tools.engram_ns import register_engram_tools
from engram.tools.lint import DescriptionLintError, assert_lint, lint_engram_namespace
from engram.tools.registry import ToolRegistry, ToolSpec


async def _noop(_args: dict) -> dict:
    return {"result": None, "meta": {}}


def _spec(name: str, description: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        input_schema={"type": "object"},
        handler=_noop,
    )


def test_all_engram_tools_pass_lint(tmp_path: Path) -> None:
    registry = ToolRegistry()
    register_engram_tools(registry, tmp_path / "anchors.sqlite", supervisor=None)
    issues = lint_engram_namespace(registry)
    assert issues == [], "\n".join(issues)


def test_lint_rejects_single_line() -> None:
    registry = ToolRegistry()
    registry.register(_spec("engram.bad", "only one line"))
    issues = lint_engram_namespace(registry)
    assert any("at least 2 lines" in i for i in issues)


def test_lint_rejects_bad_line2_prefix() -> None:
    registry = ToolRegistry()
    registry.register(_spec("engram.bad", "Does a thing.\nThis line is wrong."))
    issues = lint_engram_namespace(registry)
    assert any("must start with" in i for i in issues)


def test_lint_skips_other_namespaces() -> None:
    registry = ToolRegistry()
    registry.register(_spec("code.find_symbol", "anything goes"))
    registry.register(_spec("mem.add", "anything goes"))
    registry.register(_spec("vec.search", "anything goes"))
    assert lint_engram_namespace(registry) == []


def test_assert_lint_raises() -> None:
    registry = ToolRegistry()
    registry.register(_spec("engram.broken", "Line 1.\nOops."))
    with pytest.raises(DescriptionLintError):
        assert_lint(registry)

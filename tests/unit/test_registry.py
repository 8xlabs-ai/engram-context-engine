from __future__ import annotations

import pytest

from engram.tools.registry import DuplicateToolError, ToolRegistry, ToolSpec


def _spec(name: str) -> ToolSpec:
    async def handler(_args: dict) -> dict:  # pragma: no cover - not invoked
        return {"result": name, "meta": {}}

    return ToolSpec(
        name=name,
        description=f"{name}\nPrefer this for tests.",
        input_schema={"type": "object"},
        handler=handler,
    )


def test_register_and_lookup() -> None:
    registry = ToolRegistry()
    registry.register(_spec("engram.health"))
    assert "engram.health" in registry
    assert registry.get("engram.health") is not None
    assert len(registry) == 1


def test_duplicate_name_raises() -> None:
    registry = ToolRegistry()
    registry.register(_spec("code.find_symbol"))
    with pytest.raises(DuplicateToolError, match="code.find_symbol"):
        registry.register(_spec("code.find_symbol"))


def test_names_sorted_across_namespaces() -> None:
    registry = ToolRegistry()
    for n in ["vec.search", "code.find_symbol", "engram.health", "mem.add"]:
        registry.register(_spec(n))
    assert registry.names() == [
        "code.find_symbol",
        "engram.health",
        "mem.add",
        "vec.search",
    ]

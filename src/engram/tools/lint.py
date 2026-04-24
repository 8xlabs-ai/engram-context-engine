from __future__ import annotations

from engram.tools.registry import ToolRegistry, ToolSpec

LINE2_PREFIXES = ("Prefer ", "Use when ")


class DescriptionLintError(ValueError):
    pass


def lint_engram_namespace(registry: ToolRegistry) -> list[str]:
    """Return a list of lint violations for engram.* tools. Empty list = pass."""
    problems: list[str] = []
    for spec in registry.specs():
        if not spec.name.startswith("engram."):
            continue
        problems.extend(_lint_one(spec))
    return problems


def _lint_one(spec: ToolSpec) -> list[str]:
    issues: list[str] = []
    lines = spec.description.splitlines()
    if len(lines) < 2:
        issues.append(f"{spec.name}: description must have at least 2 lines")
        return issues
    line1, line2 = lines[0].strip(), lines[1].strip()
    if not line1:
        issues.append(f"{spec.name}: line 1 empty")
    if len(line1) > 120:
        issues.append(f"{spec.name}: line 1 exceeds 120 chars ({len(line1)})")
    if not any(line2.startswith(p) for p in LINE2_PREFIXES):
        issues.append(
            f"{spec.name}: line 2 must start with one of {LINE2_PREFIXES}, got "
            f"{line2!r}"
        )
    return issues


def assert_lint(registry: ToolRegistry) -> None:
    issues = lint_engram_namespace(registry)
    if issues:
        raise DescriptionLintError("\n".join(issues))

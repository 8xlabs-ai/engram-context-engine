"""engram.contradicts — invoke MemPalace fact_checker.check_text out-of-band.

MemPalace ships a fact_checker.py module that is importable but not wired
into its write path (02 §5). Engram calls it directly:

- Preferred: in-process import `from mempalace import fact_checker`. Cheap
  when MemPalace is already a pip dep of Engram.
- Fallback: subprocess `python -m mempalace.fact_checker "<text>"` and
  parse stdout.

If neither path works, return error-code `fact-checker-unavailable`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from engram.tools.envelope import failure, latency_meter, success
from engram.tools.registry import ToolHandler, ToolRegistry, ToolSpec

log = logging.getLogger("engram.contradicts")

CONTRADICTS_DESCRIPTION = (
    "Run MemPalace's fact_checker against a candidate text and surface contradictions.\n"
    "Use when you're about to write a memory and want to catch conflicts before it lands."
)

CheckText = Callable[[str, dict[str, Any]], Awaitable[list[dict[str, Any]] | None]]


def register_contradicts(registry: ToolRegistry, check: CheckText | None = None) -> None:
    checker = check or _default_check_text

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            text = args.get("text")
            wing = args.get("wing")
            if not isinstance(text, str) or not text:
                return failure(
                    "invalid-input",
                    "text is required",
                    meta_extra={"latency_ms": m["latency_ms"]},
                )
            extras: dict[str, Any] = {}
            if isinstance(wing, str) and wing:
                extras["wing"] = wing
            try:
                issues = await checker(text, extras)
            except Exception as exc:  # noqa: BLE001
                log.exception("fact_checker raised")
                return failure(
                    "fact-checker-unavailable",
                    f"fact_checker raised: {exc}",
                    meta_extra={"latency_ms": m["latency_ms"]},
                )
            if issues is None:
                return failure(
                    "fact-checker-unavailable",
                    "mempalace.fact_checker could not be loaded via import or subprocess",
                    meta_extra={"latency_ms": m["latency_ms"]},
                )
        return success(
            {"issues": issues},
            meta_extra={"latency_ms": m["latency_ms"]},
        )

    registry.register(
        ToolSpec(
            name="engram.contradicts",
            description=CONTRADICTS_DESCRIPTION,
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "wing": {"type": "string"},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
            handler=handler,
        )
    )


async def _default_check_text(
    text: str, extras: dict[str, Any]
) -> list[dict[str, Any]] | None:
    in_process = _call_in_process(text, extras)
    if in_process is not None:
        return in_process
    return await _call_subprocess(text, extras)


def _call_in_process(text: str, extras: dict[str, Any]) -> list[dict[str, Any]] | None:
    try:
        from mempalace import fact_checker  # type: ignore[attr-defined]
    except Exception:
        return None
    try:
        issues = fact_checker.check_text(text, **extras)
    except TypeError:
        # Older MemPalace signatures may not accept kwargs.
        try:
            issues = fact_checker.check_text(text)
        except Exception:
            return None
    except Exception:
        return None
    return _normalize(issues)


async def _call_subprocess(text: str, extras: dict[str, Any]) -> list[dict[str, Any]] | None:
    loop = asyncio.get_running_loop()
    def run() -> list[dict[str, Any]] | None:
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "mempalace.fact_checker", text],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        if completed.returncode != 0:
            return None
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return None
        return _normalize(payload)

    return await loop.run_in_executor(None, run)


def _normalize(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        for key in ("issues", "results", "items"):
            inner = value.get(key)
            if isinstance(inner, list):
                return [v for v in inner if isinstance(v, dict)]
    return []

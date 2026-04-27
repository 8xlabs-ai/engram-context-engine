#!/usr/bin/env python3
"""Claude Code PostToolUse hook shim for Engram.

Reads a PostToolUse event JSON from stdin, filters to file-mutating tools
(Edit/Write/NotebookEdit), and appends one JSON line to
`<workspace>/.engram/inbox/hook_events.jsonl`.

The Engram MCP server tails that JSONL inbox via `HookInboxTailer`. The
script is stdlib-only so it can ship with Engram and be invoked by the
Claude Code harness without any environment setup.

Always exits 0 — this hook is fire-and-forget. Any error is silenced so
that hook failures never block Claude Code's tool execution.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ALLOWED_TOOLS = {"Edit", "Write", "NotebookEdit"}


def _resolve_workspace(cwd: str | None) -> Path | None:
    """Walk up from cwd looking for a `.engram` directory.

    If none is found, fall back to cwd itself (we'll create .engram/inbox).
    Returns None only if cwd is empty/invalid.
    """
    if not cwd:
        cwd = os.getcwd()
    path = Path(cwd).resolve()
    cursor: Path | None = path
    while cursor is not None:
        if (cursor / ".engram").is_dir():
            return cursor
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent
    return path  # fall back: cwd itself


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        event = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return 0

    if event.get("hook_event_name") != "PostToolUse":
        return 0
    tool_name = event.get("tool_name")
    if tool_name not in ALLOWED_TOOLS:
        return 0

    tool_input = event.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        return 0

    response = event.get("tool_response") or {}
    if response and response.get("success") is False:
        return 0

    workspace = _resolve_workspace(event.get("cwd"))
    if workspace is None:
        return 0

    inbox_dir = workspace / ".engram" / "inbox"
    try:
        inbox_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return 0

    inbox_path = inbox_dir / "hook_events.jsonl"
    line = json.dumps(
        {
            "hook_event_name": event.get("hook_event_name"),
            "tool_name": tool_name,
            "tool_input": {"file_path": file_path},
            "tool_response": {"success": response.get("success", True)},
            "session_id": event.get("session_id"),
            "tool_use_id": event.get("tool_use_id"),
            "transcript_path": event.get("transcript_path"),
            "cwd": event.get("cwd"),
        },
        sort_keys=True,
    )
    try:
        with inbox_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

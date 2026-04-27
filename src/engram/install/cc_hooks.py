"""Idempotent installer for Engram's Claude Code PostToolUse hook.

On Engram server startup we ensure that `<workspace>/.claude/settings.local.json`
contains a `PostToolUse` entry pointing at our hook shim script. The merge
is idempotent: re-running never duplicates the entry, and existing user
hooks are preserved.

Disable via `cc_hook_install.enabled = false` in `engram.toml` or the
`ENGRAM_DISABLE_HOOK_INSTALL=1` env var.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any

log = logging.getLogger("engram.install.cc_hooks")

HOOK_MATCHER = "Edit|Write|NotebookEdit"
HOOK_TYPE = "command"
HOOK_MARKER = "engram-post-tool-hook"  # signature for our entry


def hook_script_path() -> Path:
    """Absolute path to the shipped cc_post_tool_hook.py script."""
    return Path(str(files("engram.scripts").joinpath("cc_post_tool_hook.py")))


def _hook_command() -> str:
    script = hook_script_path()
    # Quote path so spaces in workspace paths survive shell parsing.
    return f'"{sys.executable}" "{script}"  # {HOOK_MARKER}'


def maybe_install_cc_hooks(workspace: Path, *, enabled: bool = True) -> bool:
    """Ensure the PostToolUse hook is registered. Returns True if a write happened."""
    if not enabled or os.environ.get("ENGRAM_DISABLE_HOOK_INSTALL") == "1":
        return False
    settings_path = workspace / ".claude" / "settings.local.json"
    try:
        return _install_into(settings_path)
    except Exception:  # noqa: BLE001
        log.exception("cc hook install failed; continuing without")
        return False


def _install_into(settings_path: Path) -> bool:
    settings = _load(settings_path)
    hooks = settings.setdefault("hooks", {})
    post_tool_use = hooks.setdefault("PostToolUse", [])

    desired_command = _hook_command()
    for matcher_block in post_tool_use:
        if not isinstance(matcher_block, dict):
            continue
        if matcher_block.get("matcher") != HOOK_MATCHER:
            continue
        existing = matcher_block.setdefault("hooks", [])
        for entry in existing:
            if not isinstance(entry, dict):
                continue
            if entry.get("type") == HOOK_TYPE and HOOK_MARKER in str(
                entry.get("command", "")
            ):
                # Already registered; ensure command points at the current path
                if entry.get("command") != desired_command:
                    entry["command"] = desired_command
                    _write(settings_path, settings)
                    log.info("cc hook command updated at %s", settings_path)
                    return True
                return False
        existing.append({"type": HOOK_TYPE, "command": desired_command})
        _write(settings_path, settings)
        log.info("cc hook appended to existing matcher in %s", settings_path)
        return True

    post_tool_use.append(
        {
            "matcher": HOOK_MATCHER,
            "hooks": [{"type": HOOK_TYPE, "command": desired_command}],
        }
    )
    _write(settings_path, settings)
    log.info("cc hook installed in %s", settings_path)
    return True


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        log.warning("settings.local.json unreadable at %s; starting fresh", path)
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, path)

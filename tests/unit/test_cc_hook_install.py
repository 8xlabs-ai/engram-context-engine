from __future__ import annotations

import json
from pathlib import Path

from engram.install.cc_hooks import (
    HOOK_MARKER,
    HOOK_MATCHER,
    hook_script_path,
    maybe_install_cc_hooks,
)


def _settings(workspace: Path) -> Path:
    return workspace / ".claude" / "settings.local.json"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_installer_creates_settings_file(tmp_path: Path) -> None:
    assert maybe_install_cc_hooks(tmp_path) is True
    data = _read(_settings(tmp_path))
    blocks = data["hooks"]["PostToolUse"]
    assert len(blocks) == 1
    assert blocks[0]["matcher"] == HOOK_MATCHER
    assert HOOK_MARKER in blocks[0]["hooks"][0]["command"]


def test_installer_is_idempotent(tmp_path: Path) -> None:
    assert maybe_install_cc_hooks(tmp_path) is True
    assert maybe_install_cc_hooks(tmp_path) is False
    data = _read(_settings(tmp_path))
    assert len(data["hooks"]["PostToolUse"]) == 1
    assert len(data["hooks"]["PostToolUse"][0]["hooks"]) == 1


def test_installer_preserves_other_hooks(tmp_path: Path) -> None:
    settings_path = _settings(tmp_path)
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PostToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [{"type": "command", "command": "echo bash"}],
                        }
                    ],
                    "Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}],
                }
            }
        ),
        encoding="utf-8",
    )

    assert maybe_install_cc_hooks(tmp_path) is True
    data = _read(settings_path)
    matchers = [b["matcher"] for b in data["hooks"]["PostToolUse"]]
    assert "Bash" in matchers and HOOK_MATCHER in matchers
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo stop"


def test_installer_appends_into_existing_matcher(tmp_path: Path) -> None:
    settings_path = _settings(tmp_path)
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PostToolUse": [
                        {
                            "matcher": HOOK_MATCHER,
                            "hooks": [
                                {"type": "command", "command": "echo unrelated"}
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    assert maybe_install_cc_hooks(tmp_path) is True
    data = _read(settings_path)
    block = data["hooks"]["PostToolUse"][0]
    commands = [h["command"] for h in block["hooks"]]
    assert "echo unrelated" in commands
    assert any(HOOK_MARKER in c for c in commands)


def test_installer_disabled(tmp_path: Path) -> None:
    assert maybe_install_cc_hooks(tmp_path, enabled=False) is False
    assert not _settings(tmp_path).exists()


def test_hook_script_path_resolves() -> None:
    path = hook_script_path()
    assert path.name == "cc_post_tool_hook.py"
    assert path.exists()

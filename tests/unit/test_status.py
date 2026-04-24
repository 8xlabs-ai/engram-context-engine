from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from engram.cli import main


def _init(tmp_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(
        main,
        [
            "init",
            "--workspace",
            str(tmp_path),
            "--embedding-provider",
            "Ollama",
            "--skip-prereq-check",
        ],
    )


def test_status_json(tmp_path: Path) -> None:
    _init(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["status", "--workspace", str(tmp_path), "--skip-upstreams", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip())
    assert payload["result"]["engram_version"]
    assert set(payload["result"]["upstreams"]) == {
        "serena",
        "mempalace",
        "claude_context",
    }


def test_status_table(tmp_path: Path) -> None:
    _init(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["status", "--workspace", str(tmp_path), "--skip-upstreams"],
    )
    assert result.exit_code == 0, result.output
    for needle in ("serena", "mempalace", "claude_context", "anchor store", "symbols"):
        assert needle in result.output

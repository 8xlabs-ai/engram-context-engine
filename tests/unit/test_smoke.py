from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from engram.cli import main


def _init(tmp_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(
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
    assert res.exit_code == 0, res.output


def test_smoke_skip_upstreams_exits_zero(tmp_path: Path) -> None:
    _init(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["smoke-test", "--workspace", str(tmp_path), "--skip-upstreams"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip())
    # With no upstreams wired, status is "down" but smoke-test still exits 0
    # because --skip-upstreams was passed.
    assert payload["meta"]["protocol_version"] == "v1"
    assert payload["result"]["status"] == "down"


def test_smoke_without_init_fails(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["smoke-test", "--workspace", str(tmp_path), "--skip-upstreams"],
    )
    assert result.exit_code == 1
    assert "run `engram init` first" in result.output

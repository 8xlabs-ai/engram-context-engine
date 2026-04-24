from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from engram.cli import main

REPO = Path(__file__).parents[2]


def test_plist_template_shipped() -> None:
    plist = REPO / "deploy/units/ai.engram.plist"
    assert plist.exists()
    text = plist.read_text(encoding="utf-8")
    assert "<key>Label</key>" in text
    assert "ai.engram" in text
    assert "ENGRAM_WORKSPACE" in text
    assert "<key>KeepAlive</key>" in text


def test_systemd_unit_template_shipped() -> None:
    unit = REPO / "deploy/units/engram.service"
    assert unit.exists()
    text = unit.read_text(encoding="utf-8")
    assert "[Service]" in text
    assert "ExecStart=" in text
    assert "Restart=on-failure" in text
    assert "ENGRAM_WORKSPACE" in text


def test_cli_supervisor_show_darwin_prints_plist() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["supervisor", "show", "--platform", "darwin"])
    assert result.exit_code == 0, result.output
    assert "ai.engram" in result.output
    assert "ENGRAM_WORKSPACE" in result.output


def test_cli_supervisor_show_linux_prints_service() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["supervisor", "show", "--platform", "linux"])
    assert result.exit_code == 0, result.output
    assert "[Service]" in result.output
    assert "ExecStart" in result.output

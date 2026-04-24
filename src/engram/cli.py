from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import click

from engram import __version__
from engram.config import EmbeddingProvider, Config, default_config
from engram.link.store import init_db


CONFIG_RELPATH = ".engram/config.yaml"
DB_RELPATH = ".engram/anchors.sqlite"

EMBEDDING_CHOICES: tuple[EmbeddingProvider, ...] = (
    "Ollama",
    "OpenAI",
    "VoyageAI",
    "Gemini",
    "OpenRouter",
)


@click.group(help="Engram — unified coding-agent substrate.")
@click.version_option(__version__, prog_name="engram")
def main() -> None:
    pass


@main.command("init", help="Bootstrap an Engram workspace.")
@click.option(
    "--workspace",
    "workspace_dir",
    default=".",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    help="Workspace root (default: current directory).",
)
@click.option(
    "--embedding-provider",
    type=click.Choice(EMBEDDING_CHOICES, case_sensitive=True),
    default="Ollama",
    show_default=True,
)
@click.option("--force", is_flag=True, help="Overwrite existing .engram/config.yaml.")
@click.option("--skip-prereq-check", is_flag=True, help="Skip Python/Node/Docker checks.")
def init_cmd(
    workspace_dir: Path,
    embedding_provider: EmbeddingProvider,
    force: bool,
    skip_prereq_check: bool,
) -> None:
    workspace = workspace_dir.resolve()
    if not workspace.exists():
        _fail(f"workspace directory does not exist: {workspace}")

    if not skip_prereq_check:
        _check_prereqs()

    config_path = workspace / CONFIG_RELPATH
    if config_path.exists() and not force:
        _fail(f"{CONFIG_RELPATH} already exists; pass --force to overwrite")

    cfg = default_config(workspace_name=workspace.name, embedding_provider=embedding_provider)
    cfg.dump(config_path)

    db_path = workspace / DB_RELPATH
    conn = init_db(db_path)
    conn.close()

    click.echo(
        json.dumps(
            {
                "workspace": str(workspace),
                "config": str(config_path.relative_to(workspace)),
                "anchor_db": str(db_path.relative_to(workspace)),
                "embedding_provider": embedding_provider,
            }
        )
    )


@main.command("status", help="Print workspace status (stub until M0 1.9).")
@click.option(
    "--workspace",
    "workspace_dir",
    default=".",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
)
def status_cmd(workspace_dir: Path) -> None:
    workspace = workspace_dir.resolve()
    config_path = workspace / CONFIG_RELPATH
    if not config_path.exists():
        _fail(f"no {CONFIG_RELPATH} found at {workspace}; run `engram init` first")
    cfg = Config.load(config_path)
    click.echo(json.dumps({"workspace": cfg.workspace.model_dump(), "version": cfg.version}))


@main.command("mcp", help="Start the Engram MCP stdio server (stub until M0 1.3).")
def mcp_cmd() -> None:
    from engram import server

    raise SystemExit(server.main())


@main.command("smoke-test", help="End-to-end plumbing check (stub until M0 1.8).")
def smoke_test_cmd() -> None:
    _fail("smoke-test not implemented yet (M0 1.8)")


@main.command("reconcile", help="Invoke the reconciler (stub until M3 4.5).")
@click.option(
    "--scope",
    type=click.Choice(["symbols", "chunks", "memories", "all"]),
    default="all",
)
@click.option("--dry-run", is_flag=True)
def reconcile_cmd(scope: str, dry_run: bool) -> None:
    _fail("reconcile not implemented yet (M3 4.5)")


def _fail(message: str) -> None:
    click.echo(f"engram: {message}", err=True)
    raise SystemExit(1)


def _check_prereqs() -> None:
    if sys.version_info < (3, 11):
        _fail(f"Python ≥3.11 required, found {sys.version.split()[0]}")

    node = shutil.which("node")
    if node is None:
        _fail(
            "node not found on PATH. Install Node ≥20 <24 "
            "(see engram/09-repo-layout-and-setup.md §6.1)."
        )
    node_major = _node_major(node)
    if node_major is None or not (20 <= node_major < 24):
        _fail(f"Node ≥20 <24 required, found v{node_major}")

    if shutil.which("docker") is None:
        _fail("docker not found on PATH (required for Milvus + Ollama via compose).")


def _node_major(node_bin: str) -> int | None:
    try:
        out = subprocess.run(
            [node_bin, "--version"], check=True, capture_output=True, text=True, timeout=5
        )
    except (subprocess.SubprocessError, OSError):
        return None
    version = out.stdout.strip().lstrip("v")
    try:
        return int(version.split(".")[0])
    except (ValueError, IndexError):
        return None


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True)


if __name__ == "__main__":
    main()

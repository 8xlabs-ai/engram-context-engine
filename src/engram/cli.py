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


@main.command("status", help="Print workspace health + anchor-store summary.")
@click.option(
    "--workspace",
    "workspace_dir",
    default=".",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of a table.")
@click.option(
    "--skip-upstreams",
    is_flag=True,
    help="Do not launch upstream MCP subprocesses; report as not connected.",
)
def status_cmd(workspace_dir: Path, as_json: bool, skip_upstreams: bool) -> None:
    import asyncio

    from engram.server import _bindings_for, build_registry
    from engram.upstream.supervisor import Supervisor, specs_from_config

    workspace = workspace_dir.resolve()
    config_path = workspace / CONFIG_RELPATH
    if not config_path.exists():
        _fail(f"no {CONFIG_RELPATH} found at {workspace}; run `engram init` first")
    cfg = Config.load(config_path)

    async def run() -> dict:
        specs = [] if skip_upstreams else specs_from_config(cfg)
        async with Supervisor(specs=specs) as supervisor:
            registry = build_registry(
                cfg,
                workspace,
                proxies=_bindings_for(supervisor, workspace / cfg.anchors.db_path),
                supervisor=supervisor,
            )
            spec = registry.get("engram.health")
            assert spec is not None
            return await spec.handler({})

    payload = asyncio.run(run())
    if as_json:
        click.echo(json.dumps(payload, sort_keys=True))
        return

    r = payload.get("result", {})
    ups = r.get("upstreams", {})
    anchors = r.get("anchor_store", {})
    click.echo(f"engram {r.get('engram_version', '?')}")
    click.echo(f"  workspace: {workspace}")
    click.echo(f"  anchor db: {workspace / cfg.anchors.db_path}")
    click.echo(f"  status:    {r.get('status', '?')}")
    click.echo("  upstreams:")
    for name in ("serena", "mempalace", "claude_context"):
        u = ups.get(name, {})
        ok = "ok" if u.get("ok") else "down"
        latency = u.get("latency_ms")
        suffix = f" ({latency} ms)" if latency is not None else ""
        reason = f" [{u.get('reason', '')}]" if not u.get("ok") and u.get("reason") else ""
        click.echo(f"    {name:<15} {ok}{suffix}{reason}")
    click.echo("  anchor store:")
    for k in ("symbols", "anchors_symbol_memory", "anchors_symbol_chunk"):
        click.echo(f"    {k:<22} {anchors.get(k, 0)}")


@main.command("mcp", help="Start the Engram MCP stdio server.")
@click.option(
    "--workspace",
    "workspace_dir",
    default=None,
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    help="Workspace root (default: $ENGRAM_WORKSPACE or CWD).",
)
def mcp_cmd(workspace_dir: Path | None) -> None:
    import os

    from engram import server

    if workspace_dir is not None:
        os.environ["ENGRAM_WORKSPACE"] = str(workspace_dir.resolve())
    raise SystemExit(server.main())


@main.command("smoke-test", help="End-to-end plumbing check.")
@click.option(
    "--workspace",
    "workspace_dir",
    default=".",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
)
@click.option(
    "--skip-upstreams",
    is_flag=True,
    help="Do not launch upstream MCP subprocesses; probe registry only.",
)
def smoke_test_cmd(workspace_dir: Path, skip_upstreams: bool) -> None:
    import asyncio

    from engram.config import Config
    from engram.server import _bindings_for, build_registry
    from engram.upstream.supervisor import Supervisor, specs_from_config

    workspace = workspace_dir.resolve()
    config_path = workspace / CONFIG_RELPATH
    if not config_path.exists():
        _fail(f"no {CONFIG_RELPATH} at {workspace}; run `engram init` first")

    async def run() -> dict:
        config = Config.load(config_path)
        specs = [] if skip_upstreams else specs_from_config(config)
        async with Supervisor(specs=specs) as supervisor:
            registry = build_registry(
                config,
                workspace,
                proxies=_bindings_for(supervisor, workspace / config.anchors.db_path),
                supervisor=supervisor,
            )
            spec = registry.get("engram.health")
            assert spec is not None
            return await spec.handler({})

    payload = asyncio.run(run())
    click.echo(json.dumps(payload, sort_keys=True))
    if "error" in payload:
        raise SystemExit(1)
    if skip_upstreams:
        raise SystemExit(0)
    if payload["result"]["status"] != "ok":
        _fail(f"engram.health returned status={payload['result']['status']}")


@main.group("supervisor", help="OS-level supervisor unit helpers.")
def supervisor_group() -> None:
    pass


@supervisor_group.command("show", help="Print the bundled launchd/systemd unit templates.")
@click.option(
    "--platform",
    "platform_name",
    type=click.Choice(["darwin", "linux"]),
    default=None,
    help="Override auto-detected platform.",
)
def supervisor_show_cmd(platform_name: str | None) -> None:
    from importlib.resources import files

    chosen = platform_name or ("darwin" if sys.platform == "darwin" else "linux")
    filename = "ai.engram.plist" if chosen == "darwin" else "engram.service"
    try:
        resource = files("engram").joinpath(f"../deploy/units/{filename}")
        # Fall back to repo path when running from source
        path = Path(str(resource)).resolve()
        if not path.exists():
            path = Path(__file__).parents[2] / "deploy" / "units" / filename
        click.echo(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _fail(f"unit template not bundled: {filename}")


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

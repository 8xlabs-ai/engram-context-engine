from __future__ import annotations

from pathlib import Path, PurePosixPath


def normalize_path(path: str | Path, workspace_root: Path) -> str:
    p = Path(path)
    if p.is_absolute():
        p = p.resolve().relative_to(workspace_root.resolve())
    return str(PurePosixPath(p))

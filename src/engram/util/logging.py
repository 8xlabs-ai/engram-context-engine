from __future__ import annotations

import logging
from pathlib import Path


def configure(level: str = "INFO", file: Path | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if file is not None:
        file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(file, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )

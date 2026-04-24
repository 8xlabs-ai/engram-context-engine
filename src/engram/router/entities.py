"""Entity extractor — regex-driven for v1.

Pulls three kinds of entities from a free-text query:
- symbol name_paths (Class/method or Class.method style),
- file paths (anything with /.../ and a recognizable extension),
- decision entities (snake_case tokens heuristically).

Good enough for the router's Path-C fact-weighted dispatch. No ML. No NER.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SYMBOL_PATH = re.compile(
    r"\b([A-Z][A-Za-z0-9_]*(?:[./][A-Za-z_][A-Za-z0-9_]*)+)\b"
)
FILE_PATH = re.compile(
    r"\b([A-Za-z0-9_\-./]+/[A-Za-z0-9_\-]+\.(?:py|ts|tsx|js|jsx|go|rb|java|rs|kt|cc|cpp|h|hpp|md|yaml|yml|json))\b"
)
SNAKE_DECISION = re.compile(r"\b([a-z][a-z0-9_]{4,}_[a-z0-9_]+)\b")


@dataclass(frozen=True)
class Entities:
    symbols: list[str]
    files: list[str]
    decisions: list[str]


def extract_entities(text: str) -> Entities:
    symbols = _dedupe(
        s.replace(".", "/") for s in SYMBOL_PATH.findall(text) if "." in s or "/" in s
    )
    files = _dedupe(FILE_PATH.findall(text))
    # Any snake_case token that appears inside a captured file path is the
    # file's stem, not a separate decision entity. Build a substring stop set.
    stop_blob = "\n".join(files)
    decisions = _dedupe(
        d for d in SNAKE_DECISION.findall(text) if d not in stop_blob
    )
    return Entities(symbols=symbols, files=files, decisions=decisions)


def _dedupe(items) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        if item not in seen:
            seen[item] = None
    return list(seen)

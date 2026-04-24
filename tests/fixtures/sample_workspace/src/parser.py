"""JSON parsing helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class Parser:
    strict: bool = True

    def parse_json(self, row: str) -> dict:
        try:
            return json.loads(row)
        except json.JSONDecodeError:
            if self.strict:
                raise
            return {}

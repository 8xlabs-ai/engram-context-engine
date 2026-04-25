"""Minimal pipeline used by Engram smoke + router fixture tests."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .parser import Parser
from .utils import chunked


@dataclass
class Pipeline:
    parser: Parser
    batch_size: int = 100

    def process_batch(self, records: Iterable[str]) -> list[dict]:
        """Parse records in fixed-size batches and flatten the result.

        Batch size defaults to 100 because the upstream API accepts at most
        that many rows per call.
        """
        out: list[dict] = []
        for batch in chunked(records, self.batch_size):
            out.extend(self.parser.parse_json(row) for row in batch)
        return out

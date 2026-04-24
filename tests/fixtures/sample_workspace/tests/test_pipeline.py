from __future__ import annotations

import json

from src.parser import Parser
from src.pipeline import Pipeline


def test_process_batch_flattens() -> None:
    pipeline = Pipeline(parser=Parser(strict=True), batch_size=2)
    records = [json.dumps({"i": i}) for i in range(5)]
    result = pipeline.process_batch(records)
    assert [row["i"] for row in result] == [0, 1, 2, 3, 4]

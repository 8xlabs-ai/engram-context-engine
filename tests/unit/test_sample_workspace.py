from __future__ import annotations

from pathlib import Path

SAMPLE = Path(__file__).parent.parent / "fixtures" / "sample_workspace"


def test_sample_workspace_exists() -> None:
    assert SAMPLE.is_dir()
    for rel in (
        "src/pipeline.py",
        "src/parser.py",
        "src/utils.py",
        "tests/test_pipeline.py",
        "README.md",
    ):
        assert (SAMPLE / rel).exists(), f"missing: {rel}"


def test_sample_workspace_symbols_are_grep_findable() -> None:
    pipeline_src = (SAMPLE / "src/pipeline.py").read_text(encoding="utf-8")
    parser_src = (SAMPLE / "src/parser.py").read_text(encoding="utf-8")
    assert "class Pipeline" in pipeline_src
    assert "def process_batch" in pipeline_src
    assert "class Parser" in parser_src
    assert "def parse_json" in parser_src

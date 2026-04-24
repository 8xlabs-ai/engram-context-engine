from __future__ import annotations

from engram.router.entities import extract_entities


def test_extracts_symbol_paths() -> None:
    e = extract_entities("rename Foo.process to run in src/foo.py")
    assert "Foo/process" in e.symbols


def test_extracts_file_paths() -> None:
    e = extract_entities("look at src/pipeline/foo.py line 42")
    assert "src/pipeline/foo.py" in e.files


def test_extracts_decision_snake_case() -> None:
    e = extract_entities("drove the graphql_migration decision into the planner")
    assert "graphql_migration" in e.decisions


def test_dedupes_repeats() -> None:
    e = extract_entities("src/foo.py and src/foo.py again; Foo.process again Foo.process")
    assert e.files == ["src/foo.py"]
    assert e.symbols == ["Foo/process"]


def test_does_not_double_count_file_as_decision() -> None:
    e = extract_entities("touch src/pipeline/graphql_migration.py")
    assert "src/pipeline/graphql_migration.py" in e.files
    assert "graphql_migration" not in e.decisions

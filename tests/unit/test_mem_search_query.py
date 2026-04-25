from __future__ import annotations

from engram.tools.engram_ns import MEM_SEARCH_QUERY_MAX, _to_keyword_query


def test_replaces_slash_with_space() -> None:
    assert _to_keyword_query("Pipeline/process_batch") == "Pipeline process_batch"


def test_replaces_dot_with_space() -> None:
    assert _to_keyword_query("Foo.bar") == "Foo bar"


def test_collapses_whitespace() -> None:
    assert _to_keyword_query("  many   spaces\nhere  ") == "many spaces here"


def test_truncates_to_max() -> None:
    long = "a" * 500
    assert len(_to_keyword_query(long)) == MEM_SEARCH_QUERY_MAX


def test_empty_returns_empty() -> None:
    assert _to_keyword_query("") == ""
    assert _to_keyword_query("   ") == ""


def test_passes_through_normal_text() -> None:
    assert _to_keyword_query("hash password bcrypt") == "hash password bcrypt"

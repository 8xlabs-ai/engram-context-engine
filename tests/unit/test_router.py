from __future__ import annotations

import pytest

from engram.router.classifier import classify_query
from engram.router.fusion import rrf_fuse


def test_classify_path_b_when_name_path_only() -> None:
    assert classify_query({"name_path": "Foo/process", "relative_path": "src/foo.py"}) == "B"


def test_classify_path_a_when_query_only() -> None:
    assert classify_query({"query": "parse json"}) == "A"
    assert classify_query({"free_query": "parse json"}) == "A"


def test_classify_path_c_when_both() -> None:
    assert classify_query({"name_path": "Foo", "query": "why"}) == "C"


def test_classify_fusion_override() -> None:
    # An engram.* composed tool can force fusion.
    assert classify_query({"name_path": "Foo", "fusion": True}) == "C"


def test_classify_blank_query_falls_back_to_B() -> None:
    assert classify_query({"name_path": "Foo", "query": "   "}) == "B"


def test_classify_empty_input_defaults_to_A() -> None:
    # Edge case — no inputs. Treated as Path A so the router dispatches to
    # claude-context with an empty query (which will return empty results).
    assert classify_query({}) == "A"


# -----------------------------------------------------------------------------
# RRF
# -----------------------------------------------------------------------------


def test_rrf_simple_three_lists() -> None:
    lists = {
        "vec": ["a", "b", "c"],
        "mem": ["b", "d", "a"],
        "kg": ["c", "a", "d"],
    }
    fused = rrf_fuse(lists, k=60, limit=10)
    order = [f.item for f in fused]

    # Hand-computed: scores (k=60)
    #   a: 1/61 + 1/63 + 1/62 ≈ 0.04818
    #   b: 1/62 + 1/61           ≈ 0.03253
    #   c: 1/63 + 1/61           ≈ 0.03227
    #   d: 1/62 + 1/63           ≈ 0.03200
    assert order[0] == "a"
    assert order[1] == "b"
    assert order[2] == "c"
    assert order[3] == "d"


def test_rrf_truncates_to_limit() -> None:
    lists = {"vec": [f"x{i}" for i in range(30)]}
    fused = rrf_fuse(lists, limit=5)
    assert len(fused) == 5
    assert [f.item for f in fused] == ["x0", "x1", "x2", "x3", "x4"]


def test_rrf_ranks_by_source_populated() -> None:
    lists = {"vec": ["a", "b"], "mem": ["b"]}
    fused = rrf_fuse(lists)
    by_item = {f.item: f for f in fused}
    assert by_item["b"].ranks_by_source == {"vec": 2, "mem": 1}
    assert by_item["a"].ranks_by_source == {"vec": 1}


def test_rrf_survives_missing_source() -> None:
    fused = rrf_fuse({"vec": ["a", "b"], "mem": []})
    assert [f.item for f in fused] == ["a", "b"]


def test_rrf_rejects_invalid_k() -> None:
    with pytest.raises(ValueError, match="k must be positive"):
        rrf_fuse({"vec": ["a"]}, k=0)
    with pytest.raises(ValueError, match="limit must be positive"):
        rrf_fuse({"vec": ["a"]}, limit=0)

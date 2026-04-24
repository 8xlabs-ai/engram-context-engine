from __future__ import annotations

from engram.router.cache import LRUCache, canonicalize


def test_canonicalize_stable_across_dict_order() -> None:
    assert canonicalize({"a": 1, "b": 2}) == canonicalize({"b": 2, "a": 1})


def test_cache_hit_then_miss_after_invalidation() -> None:
    cache = LRUCache(max_entries=8)
    cache.put("engram.why", {"name_path": "Foo/process"}, {"result": 1})
    assert cache.get("engram.why", {"name_path": "Foo/process"}) == {"result": 1}

    removed = cache.invalidate_if(
        lambda tool, args_json: "Foo/process" in args_json
    )
    assert removed == 1
    assert cache.get("engram.why", {"name_path": "Foo/process"}) is None


def test_cache_lru_evicts_oldest_first() -> None:
    cache = LRUCache(max_entries=2)
    cache.put("a", {"i": 1}, "one")
    cache.put("a", {"i": 2}, "two")
    cache.put("a", {"i": 3}, "three")
    assert cache.get("a", {"i": 1}) is None
    assert cache.get("a", {"i": 2}) == "two"
    assert cache.get("a", {"i": 3}) == "three"


def test_cache_get_refreshes_recency() -> None:
    cache = LRUCache(max_entries=2)
    cache.put("a", {"i": 1}, "one")
    cache.put("a", {"i": 2}, "two")
    assert cache.get("a", {"i": 1}) == "one"  # i=1 becomes most-recent
    cache.put("a", {"i": 3}, "three")
    # i=2 should be evicted (oldest), i=1 survives
    assert cache.get("a", {"i": 2}) is None
    assert cache.get("a", {"i": 1}) == "one"


def test_invalidate_by_tool_name() -> None:
    cache = LRUCache()
    cache.put("engram.why", {"name_path": "Foo"}, "v1")
    cache.put("code.find_symbol", {"name_path": "Foo"}, "v2")
    removed = cache.invalidate_if(lambda tool, _: tool == "engram.why")
    assert removed == 1
    assert cache.get("engram.why", {"name_path": "Foo"}) is None
    assert cache.get("code.find_symbol", {"name_path": "Foo"}) == "v2"

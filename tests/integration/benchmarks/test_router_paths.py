"""Path A / B / C router benchmarks against fake (deterministic) sources.

Real upstream latencies vary too much to baseline (Ollama / Milvus warm-up,
LSP onboarding). These benchmarks measure router-internal overhead — fusion,
classifier, dispatcher, async fan-out — with constant-time fake sources, so
regressions in our code, not upstream, fail the gate.

Targets per `retrieval-router` spec (warm P50):
  Path A ≤ 150 ms
  Path B ≤ 100 ms
  Path C ≤ 300 ms

These thresholds bound router overhead alone. Real-upstream P50 is captured
separately under tests/integration/real_upstreams/ (not in this build).

Run with: PYTHONPATH=src .venv/bin/pytest tests/integration/benchmarks/ \\
  --benchmark-only --benchmark-columns=median,mean
"""

from __future__ import annotations

import asyncio

import pytest

from engram.router.dispatcher import RouterDispatcher

PATH_A_BUDGET_MS = 150.0
PATH_B_BUDGET_MS = 100.0
PATH_C_BUDGET_MS = 300.0


def _dispatcher() -> RouterDispatcher:
    fake_chunks = [
        {"relative_path": f"src/file{i}.py", "start_line": i, "end_line": i + 5}
        for i in range(10)
    ]
    fake_memories = [{"drawer_id": f"D{i}", "content": f"memory {i}"} for i in range(10)]
    fake_facts = [
        {"subject": "Foo", "predicate": "p", "object": f"v{i}"} for i in range(5)
    ]

    async def vec_search(_q: str, _l: int):
        return list(fake_chunks)

    async def mem_search(_q: str):
        return list(fake_memories)

    async def kg_query(_s: str):
        return list(fake_facts)

    async def symbol_lookup(name_path: str, relative_path: str):
        return {"name_path": name_path, "relative_path": relative_path, "kind": 12}

    return RouterDispatcher(
        vec_search=vec_search,
        mem_search=mem_search,
        kg_query=kg_query,
        symbol_lookup=symbol_lookup,
    )


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def dispatcher() -> RouterDispatcher:
    return _dispatcher()


def test_bench_path_a_median_under_budget(benchmark, dispatcher) -> None:
    def call() -> None:
        asyncio.run(dispatcher.dispatch({"query": "parse json"}))

    benchmark(call)
    median_ms = benchmark.stats.stats.median * 1000
    assert (
        median_ms <= PATH_A_BUDGET_MS
    ), f"path A median {median_ms:.1f}ms > budget {PATH_A_BUDGET_MS}ms"


def test_bench_path_b_median_under_budget(benchmark, dispatcher) -> None:
    def call() -> None:
        asyncio.run(
            dispatcher.dispatch(
                {"name_path": "Foo/process", "relative_path": "src/foo.py"}
            )
        )

    benchmark(call)
    median_ms = benchmark.stats.stats.median * 1000
    assert (
        median_ms <= PATH_B_BUDGET_MS
    ), f"path B median {median_ms:.1f}ms > budget {PATH_B_BUDGET_MS}ms"


def test_bench_path_c_median_under_budget(benchmark, dispatcher) -> None:
    def call() -> None:
        asyncio.run(
            dispatcher.dispatch(
                {
                    "name_path": "Foo/process",
                    "relative_path": "src/foo.py",
                    "query": "parse json",
                }
            )
        )

    benchmark(call)
    median_ms = benchmark.stats.stats.median * 1000
    assert (
        median_ms <= PATH_C_BUDGET_MS
    ), f"path C median {median_ms:.1f}ms > budget {PATH_C_BUDGET_MS}ms"

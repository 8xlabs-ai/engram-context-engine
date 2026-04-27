"""vec.search post-processor: add `enclosing_symbol` to each chunk.

Per the `mcp-proxy` spec: results from vec.search SHALL carry an
`enclosing_symbol` field, resolved from the Link Layer's
`anchors_symbol_chunk` table when possible, or on-demand via Serena when
absent. On-demand resolutions lazily seed the anchor table for next time.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from engram.link.store import open_db
from engram.tools.envelope import failure, latency_meter, success
from engram.tools.registry import ToolHandler
from engram.upstream.client import UpstreamClient

log = logging.getLogger("engram.vec_enrich")


def make_vec_search_handler(
    db_path: Path,
    vec_client: UpstreamClient,
    serena_client_getter,
) -> ToolHandler:
    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        with latency_meter() as m:
            try:
                result = await vec_client.call_tool("search_code", arguments)
            except Exception as exc:  # noqa: BLE001
                return failure(
                    "upstream-unavailable",
                    f"vec search_code failed: {exc}",
                    meta_extra={"latency_ms": m["latency_ms"], "upstream": "claude-context"},
                )
            if result.isError:
                return failure(
                    "upstream-unavailable",
                    "vec search_code returned error",
                    details=_structured(result),
                    meta_extra={"latency_ms": m["latency_ms"], "upstream": "claude-context"},
                )

            payload = _structured(result)
            chunks = _chunks_from(payload)
            serena = serena_client_getter()
            enriched = await _enrich_chunks(db_path, serena, chunks)

        response = payload if not isinstance(payload, list) else {"results": payload}
        if isinstance(response, dict):
            response["results"] = enriched
        else:
            response = {"results": enriched}

        return success(
            response,
            meta_extra={
                "latency_ms": m["latency_ms"],
                "upstream": "claude-context",
                "path_used": "A",
            },
        )

    return handler


async def _enrich_chunks(
    db_path: Path, serena: UpstreamClient | None, chunks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not chunks:
        return chunks
    conn = open_db(db_path) if db_path.exists() else None
    out: list[dict[str, Any]] = []
    try:
        for chunk in chunks:
            enriched = dict(chunk)
            enriched["enclosing_symbol"] = await resolve_chunk_symbol(conn, serena, chunk)
            out.append(enriched)
    finally:
        if conn is not None:
            conn.close()
    return out


async def resolve_chunk_symbol(
    conn, serena: UpstreamClient | None, chunk: dict[str, Any]
) -> dict[str, Any] | None:
    """Resolve a chunk's enclosing symbol via the anchor cache, then Serena.

    Used both by the `vec.search` post-processor and `engram.where_does_decision_apply`
    to populate `enclosing_symbol` from a chunk's line range — never from a
    free-text query term.
    """
    rel = chunk.get("relativePath") or chunk.get("relative_path")
    start = chunk.get("startLine") or chunk.get("start_line")
    end = chunk.get("endLine") or chunk.get("end_line")
    if not isinstance(rel, str) or not isinstance(start, int):
        return None

    # Link Layer lookup first.
    if conn is not None:
        row = conn.execute(
            "SELECT s.name_path, s.relative_path, s.kind FROM anchors_symbol_chunk asc_ "
            "JOIN symbols s ON s.symbol_id = asc_.symbol_id "
            "WHERE asc_.relative_path = ? AND asc_.start_line <= ? AND asc_.end_line >= ? "
            "ORDER BY (asc_.end_line - asc_.start_line) ASC LIMIT 1",
            (rel, start, end if isinstance(end, int) else start),
        ).fetchone()
        if row is not None:
            return {
                "name_path": row["name_path"],
                "relative_path": row["relative_path"],
                "kind": int(row["kind"]),
                "source": "anchor_cache",
            }

    # On-demand Serena resolution.
    if serena is None:
        return None
    try:
        result = await serena.call_tool(
            "get_symbols_overview", {"relative_path": rel}
        )
    except Exception:  # noqa: BLE001
        return None
    if result.isError:
        return None
    overview = _structured(result)
    symbol = _innermost_symbol_at(overview, start, end if isinstance(end, int) else start)
    if symbol is None:
        return None
    symbol = dict(symbol)
    symbol["source"] = "serena_live"
    return symbol


def _innermost_symbol_at(overview: Any, start: int, end: int) -> dict[str, Any] | None:
    if not isinstance(overview, list):
        overview = overview.get("symbols") if isinstance(overview, dict) else []
    if not isinstance(overview, list):
        return None
    best: dict[str, Any] | None = None
    best_span = None
    for item in overview:
        if not isinstance(item, dict):
            continue
        s = item.get("start_line") or item.get("startLine")
        e = item.get("end_line") or item.get("endLine")
        if not isinstance(s, int) or not isinstance(e, int):
            continue
        if s <= start and e >= end:
            span = e - s
            if best_span is None or span < best_span:
                best_span = span
                best = item
    return best


def _chunks_from(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [c for c in payload if isinstance(c, dict)]
    if isinstance(payload, dict):
        for key in ("results", "chunks", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [c for c in value if isinstance(c, dict)]
    return []


def _structured(result: Any) -> Any:
    if getattr(result, "structuredContent", None):
        return dict(result.structuredContent)
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is None:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return None

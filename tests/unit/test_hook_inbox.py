from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from engram.link.store import init_db, meta_get, open_db
from engram.scripts import cc_post_tool_hook  # noqa: F401  (import to ensure path resolves)
from engram.workers.hook_inbox import (
    META_CURSOR_KEY,
    HookInboxTailer,
    _to_notify_payload,
)


def _post_tool_event(
    *,
    tool_name: str = "Edit",
    file_path: str = "src/foo.py",
    cwd: str | None = None,
    session_id: str = "conv_abc",
    success: bool = True,
) -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": tool_name,
        "tool_input": {"file_path": file_path},
        "tool_response": {"success": success},
        "session_id": session_id,
        "tool_use_id": "toolu_1",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": cwd or "",
    }


def test_to_notify_payload_maps_edit() -> None:
    payload = _to_notify_payload(_post_tool_event())
    assert payload is not None
    assert payload["relative_path"] == "src/foo.py"
    assert payload["change_type"] == "edit"
    assert payload["source"] == "claude_code_hook"
    assert payload["agent"] == "claude_code"
    assert payload["conversation_id"] == "conv_abc"


def test_to_notify_payload_filters_other_tools() -> None:
    assert _to_notify_payload(_post_tool_event(tool_name="Read")) is None
    assert _to_notify_payload(_post_tool_event(tool_name="Bash")) is None


def test_to_notify_payload_drops_failed_calls() -> None:
    assert _to_notify_payload(_post_tool_event(success=False)) is None


def test_inbox_tailer_drains_and_persists_cursor(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    inbox = tmp_path / "inbox.jsonl"
    inbox.write_text(
        json.dumps(_post_tool_event(file_path="src/a.py")) + "\n"
        + json.dumps(_post_tool_event(file_path="src/b.py")) + "\n",
        encoding="utf-8",
    )

    received: list[dict] = []

    async def handler(p: dict) -> dict:
        received.append(p)
        return {"accepted": True}

    tailer = HookInboxTailer(
        inbox_path=inbox, db_path=db, notify_handler=handler, poll_interval_s=0.05
    )

    async def run_one_tick() -> None:
        await tailer._tick_once()

    asyncio.run(run_one_tick())

    assert [p["relative_path"] for p in received] == ["src/a.py", "src/b.py"]

    conn = open_db(db)
    try:
        cursor = int(meta_get(conn, META_CURSOR_KEY) or "0")
    finally:
        conn.close()
    assert cursor == inbox.stat().st_size


def test_inbox_tailer_resumes_after_restart(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    inbox = tmp_path / "inbox.jsonl"
    inbox.write_text(
        json.dumps(_post_tool_event(file_path="src/a.py")) + "\n",
        encoding="utf-8",
    )

    received: list[dict] = []

    async def handler(p: dict) -> dict:
        received.append(p)
        return {"accepted": True}

    tailer1 = HookInboxTailer(
        inbox_path=inbox, db_path=db, notify_handler=handler
    )
    asyncio.run(tailer1._tick_once())

    # Append another line and re-tick — only the new one should fire.
    with inbox.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_post_tool_event(file_path="src/b.py")) + "\n")

    tailer2 = HookInboxTailer(
        inbox_path=inbox, db_path=db, notify_handler=handler
    )
    asyncio.run(tailer2._tick_once())

    assert [p["relative_path"] for p in received] == ["src/a.py", "src/b.py"]


def test_inbox_tailer_handles_partial_line(tmp_path: Path) -> None:
    db = tmp_path / "anchors.sqlite"
    init_db(db).close()
    inbox = tmp_path / "inbox.jsonl"
    full = json.dumps(_post_tool_event(file_path="src/a.py")) + "\n"
    partial = json.dumps(_post_tool_event(file_path="src/b.py"))  # no newline
    inbox.write_text(full + partial, encoding="utf-8")

    received: list[dict] = []

    async def handler(p: dict) -> dict:
        received.append(p)
        return {"accepted": True}

    tailer = HookInboxTailer(
        inbox_path=inbox, db_path=db, notify_handler=handler
    )
    asyncio.run(tailer._tick_once())
    assert [p["relative_path"] for p in received] == ["src/a.py"]

    # Complete the partial line and re-tick — second event lands.
    with inbox.open("a", encoding="utf-8") as fh:
        fh.write("\n")
    asyncio.run(tailer._tick_once())
    assert [p["relative_path"] for p in received] == ["src/a.py", "src/b.py"]


def test_post_tool_hook_script_writes_jsonl(tmp_path: Path) -> None:
    workspace = tmp_path
    (workspace / ".engram").mkdir()
    script = (
        Path(__file__).parent.parent.parent
        / "src"
        / "engram"
        / "scripts"
        / "cc_post_tool_hook.py"
    )
    event = _post_tool_event(file_path=str(workspace / "src/foo.py"), cwd=str(workspace))
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    inbox = workspace / ".engram" / "inbox" / "hook_events.jsonl"
    assert inbox.exists()
    line = inbox.read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    assert parsed["tool_name"] == "Edit"
    assert parsed["session_id"] == "conv_abc"

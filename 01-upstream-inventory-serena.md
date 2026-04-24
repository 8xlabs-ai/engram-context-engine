# 01 — Upstream Inventory: Serena

> Status: **draft**. Cited investigation of the Serena repository at `/Users/zaghloul/Projects/accelerate-workspace/serena/`. Version `1.1.2`, MIT. Every structural claim carries a `serena/path:line` citation. Claims that could not be verified against the code are moved into the *Assumptions* section at the end.

Serena is an MCP-based Python toolkit that gives an AI agent LSP-backed semantic code understanding: symbol-aware lookup, cross-file references, and symbol-level edits. It bundles language servers (pyright, fortls, etc.) and fronts them behind a uniform tool surface.

## 1. Entrypoints

- **CLI.** `serena = "serena.cli:top_level"` (`serena/pyproject.toml:66`). The root `click` group is `TopLevelCommands` (`serena/src/serena/cli.py:131`). Exposed commands: `init`, `setup`, `start-mcp-server`, `print-system-prompt`, `start-project-server`, `dashboard-viewer` (`serena/src/serena/cli.py:163-486`).
- **Hooks CLI.** `serena-hooks = "serena.hooks:hook_commands"` (`serena/pyproject.toml:67`). Pre-tool-use hooks for permission + nudging (`serena/src/serena/hooks.py:29-250`).
- **MCP server.** `start-mcp-server` command constructs a `SerenaMCPFactory` (`serena/src/serena/cli.py:349`), calls `create_mcp_server()` (`serena/src/serena/mcp.py:271-344`), then `server.run(transport=...)` (`serena/src/serena/cli.py:368`).
- **Project root detection.** Walks up from CWD looking for `.serena/project.yml` first, then `.git` (`serena/src/serena/cli.py:63-93`).
- **Config files read at startup.**
  - Global: `~/.serena/serena_config.yml` (loaded via `SerenaConfig.from_config_file()` in `serena/src/serena/config/serena_config.py`).
  - Per-project: `.serena/project.yml` (`serena/src/serena/project.py:267-313`).
  - User contexts / modes: `~/.serena/contexts/*.yml`, `~/.serena/modes/*.yml` (`serena/src/serena/cli.py:73-82`).
- **Logs.** Stderr (live) and file at `~/.serena/logs/{YYYY-MM-DD}/{prefix}_{timestamp}_{pid}.txt` (`serena/src/serena/cli.py:330-333`).

## 2. MCP surface — complete tool inventory

Serena's registration pattern is **not decorator-based**; tools are discovered by subclassing. `ToolRegistry` (`serena/src/serena/tools/tools_base.py:466-488`) iterates every concrete subclass of `Tool` (those that override `apply`) inside the `serena.tools` package. Duplicate names raise `ValueError` (`tools_base.py:485-486`). Five tool names have been intentionally retired and live in `_deleted_tools` (`tools_base.py:468-474`).

Marker classes on `Tool` subclasses drive behavior: `ToolMarkerCanEdit`, `ToolMarkerSymbolicRead`, `ToolMarkerSymbolicEdit`, `ToolMarkerOptional`, `ToolMarkerDoesNotRequireActiveProject`, `ToolMarkerBeta` (`tools_base.py:80-118`).

### Core symbolic & file tools (always registered)


| Tool                                              | File:Line                                    | Inputs (type)                                                                                                                                                            | Output | Behavior                                                                                                            |
| ------------------------------------------------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------ | ------------------------------------------------------------------------------------------------------------------- |
| `restart_language_server`                         | `serena/src/serena/tools/symbol_tools.py:21` | —                                                                                                                                                                        | str    | Restarts LSP; needed when edits happen outside Serena. **Critical hint that Serena does not watch the filesystem.** |
| `get_symbols_overview`                            | `symbol_tools.py:32-39`                      | `relative_path: str`, `depth: int=0`, `max_answer_chars: int=-1`                                                                                                         | JSON   | Top-level symbols in a file, optionally with descendants.                                                           |
| `find_symbol`                                     | `symbol_tools.py:122-144`                    | `name_path_pattern`, `depth`, `relative_path`, `include_body`, `include_info`, `include_kinds`, `exclude_kinds`, `substring_matching`, `max_matches`, `max_answer_chars` | JSON   | Pattern-based symbol lookup across the project.                                                                     |
| `find_referencing_symbols`                        | `symbol_tools.py:239-326`                    | `name_path`, `relative_path`, `max_answer_chars`                                                                                                                         | JSON   | References to a symbol with surrounding code snippets.                                                              |
| `replace_symbol_body`                             | `symbol_tools.py:327-358`                    | `name_path`, `relative_path`, `body`                                                                                                                                     | str    | Replaces symbol body.                                                                                               |
| `insert_after_symbol` / `insert_before_symbol`    | `symbol_tools.py:360-409`                    | `name_path`, `relative_path`, `body`                                                                                                                                     | str    | Positional insertion relative to a symbol.                                                                          |
| `rename_symbol`                                   | `symbol_tools.py:410-435`                    | `name_path`, `relative_path`, `new_name`                                                                                                                                 | str    | Project-wide rename via LSP.                                                                                        |
| `safe_delete_symbol`                              | `symbol_tools.py:437-465`                    | `name_path_pattern`, `relative_path`                                                                                                                                     | str    | Deletes only if no references remain.                                                                               |
| `read_file`                                       | `file_tools.py:20-48`                        | `relative_path`, `start_line`, `end_line`, `max_answer_chars`                                                                                                            | str    | File (or slice) read with project-path validation.                                                                  |
| `create_text_file`                                | `file_tools.py:51-81`                        | `relative_path`, `content`                                                                                                                                               | str    | Create or overwrite UTF-8 text.                                                                                     |
| `list_dir`                                        | `file_tools.py:83-120`                       | `relative_path`, `recursive`, `skip_ignored_files`, `max_answer_chars`                                                                                                   | JSON   | Dir listing honoring ignore rules.                                                                                  |
| `find_file`                                       | `file_tools.py:123-156`                      | `file_mask`, `relative_path`                                                                                                                                             | JSON   | Non-gitignored glob match.                                                                                          |
| `replace_content`                                 | `file_tools.py:159-222`                      | `relative_path`, `needle`, `repl`, `mode(literal|regex)`, `allow_multiple_occurrences`                                                                                   | str    | Regex or literal in-file replace.                                                                                   |
| `delete_lines`, `replace_lines`, `insert_at_line` | `file_tools.py:224-306`                      | line-based params                                                                                                                                                        | str    | Line-addressed edits (optional, disabled by default — `ToolMarkerOptional`).                                        |
| `search_for_pattern`                              | `file_tools.py:308-369`                      | regex pattern + context + include/exclude globs                                                                                                                          | JSON   | Cross-file regex with context lines.                                                                                |
| `execute_shell_command`                           | `cmd_tools.py:11-72`                         | `command`, `cwd`, `capture_stderr`, `max_answer_chars`                                                                                                                   | str    | Shell exec within the project.                                                                                      |


### Memory tools


| Tool            | File:Line                | Inputs                                                                | Behavior                                                                                            |
| --------------- | ------------------------ | --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `write_memory`  | `memory_tools.py:6-30`   | `memory_name`, `content`, `max_chars`                                 | Writes markdown to `.serena/memories/{name}.md` (project) or `~/.serena/memories/global/{name}.md`. |
| `read_memory`   | `memory_tools.py:33-46`  | `memory_name`                                                         | Returns file content.                                                                               |
| `list_memories` | `memory_tools.py:49-58`  | `topic`                                                               | Lists memories, optional topic filter.                                                              |
| `delete_memory` | `memory_tools.py:61-72`  | `memory_name`                                                         | Unlinks the file.                                                                                   |
| `rename_memory` | `memory_tools.py:75-86`  | `old_name`, `new_name`                                                | Supports moving between project ↔ global scope.                                                     |
| `edit_memory`   | `memory_tools.py:89-115` | `memory_name`, `needle`, `repl`, `mode`, `allow_multiple_occurrences` | In-place regex/literal edit.                                                                        |


### Config, workflow, and multi-project tools


| Tool                                                                 | File:Line                      | Behavior                                                          |
| -------------------------------------------------------------------- | ------------------------------ | ----------------------------------------------------------------- |
| `activate_project`                                                   | `config_tools.py:22-40`        | Session-aware activation of a registered project.                 |
| `open_dashboard`                                                     | `config_tools.py:6-20`         | Opens web dashboard (optional).                                   |
| `remove_project`                                                     | `config_tools.py:42-55`        | Removes a registered project (optional).                          |
| `get_current_config`                                                 | `config_tools.py:57-75`        | Returns current active project + paths.                           |
| `list_queryable_projects`                                            | `query_project_tools.py:9-38`  | Lists cross-project queryable projects (optional).                |
| `query_project`                                                      | `query_project_tools.py:40-88` | Executes any Serena tool in another project's context (optional). |
| `check_onboarding_performed` / `onboarding` / `initial_instructions` | `workflow_tools.py:10-73`      | Session-lifecycle tools.                                          |


### JetBrains alternative surface (optional, beta)

Ten tools mirroring the core LSP surface live in `serena/src/serena/tools/jetbrains_tools.py` and are used when the language backend is set to JetBrains (`serena/src/serena/config/serena_config.py:175-199`). They are all marked `ToolMarkerOptional` + `ToolMarkerBeta`. Notable: `jetbrains_move` (`jetbrains_tools.py:126-174`) is the closest thing to a symbol-move primitive and is explicitly labeled beta.

**Total tools registered (LSP path, core + memory + workflow + config):** ≈ 30. Another ≈ 10 JetBrains-backend tools are registered when the JetBrains backend is selected. Exact counts depend on which markers are enabled.

## 3. Public Python API

`serena/src/serena/__init__.py:1-35` exports only `serena_version()` and a logging helper. There is no `__all__`, no documented library API, no stability guarantee. Third-party code is expected to consume Serena via MCP, not Python imports.

Version: `1.1.2` (`serena/pyproject.toml:7`, `__init__.py:1`). `serena_version()` appends git info if available (`__init__.py:8-23`).

Tool marker classes (`tools_base.py:80-118`) are the closest thing to a stable subclass contract. JetBrains tools carrying `ToolMarkerBeta` are explicitly flagged unstable.

## 4. Data stores / on-disk state

- **Global Serena home:** `~/.serena/` (override via `SERENA_HOME`), managed at `serena/src/serena/config/serena_config.py:52-127`.
  - `serena_config.yml` — YAML config, saved via `save_yaml()`.
  - `memories/` (+ `memories/global/`) — markdown per memory.
  - `contexts/`, `modes/`, `prompt_templates/` — user overrides.
  - `logs/YYYY-MM-DD/…txt`.
  - `hook_data/{session_id}/` — pre-tool-use state (`hooks.py:40`).
  - `news.json`, `news_read.pkl`, `news_etag.txt`, `last_read_news_snippet_id.txt` — news cache.
- **Per-project:** `.serena/` at project root.
  - `project.yml` — schema in `serena/src/serena/config/serena_config.py` (`Project.load()` at `project.py:267-313`).
  - `.serena/memories/` — project-scoped memory markdown.
  - `.serena/{CACHE_FOLDER_NAME}/{language_code}/` — language-server symbol caches (`serena/src/serena/tools/tools_base.py:386`, delegated to SolidLanguageServer via `ls_manager.py:243-249`).
  - `.serena/.gitignore` — auto-created (`project.py:299-306`) with ignore rules for cache folder + local config.
- **Memory write sites** (`serena/src/serena/project.py`):
  - Save: line 132 (`open(memory_file_path, "w")`).
  - Delete: line 216 (`memory_file_path.unlink()`).
  - Move: line 237 (`shutil.move`).
  - Edit: line 262 (rewrites file).

## 5. Extension points

- **Tool subclassing.** Any concrete class extending `Tool` with an `apply` method is auto-discovered (`tools_base.py:466-488`). No manual registration.
- **Marker subclassing.** Tools inherit `ToolMarkerOptional` / `ToolMarkerCanEdit` / `ToolMarkerSymbolicRead` / `ToolMarkerSymbolicEdit` / `ToolMarkerBeta` / `ToolMarkerDoesNotRequireActiveProject` to change visibility and routing (`tools_base.py:80-118`).
- **Hook subclassing.** `Hook` abstract base + `PreToolUseHook` for permission/nudge logic (`serena/src/serena/hooks.py:29-250`); invoked via the `serena-hooks` CLI.
- **Language-backend switch.** `LanguageBackend` enum (`config/serena_config.py:175-199`) between LSP and JetBrains; tool classes route accordingly (`tools_base.py:61-77`).
- **YAML overrides.** User YAMLs in `~/.serena/contexts/`, `~/.serena/modes/`, `~/.serena/prompt_templates/` override internals (`cli.py:508-629`).
- **No plugin registry, no pubsub, no callback hooks from core Serena to external code.** Extensions happen by subclassing within a fork or in an adjacent package that imports `Tool`.

## 6. Write paths (places where Serena touches disk)


| Op                                | File:Line                                     | Path                                                                  |
| --------------------------------- | --------------------------------------------- | --------------------------------------------------------------------- |
| Memory save                       | `project.py:132`                              | `.serena/memories/{name}.md` or `~/.serena/memories/global/{name}.md` |
| Memory delete / move / edit       | `project.py:216 / 237 / 262`                  | as above                                                              |
| Arbitrary file create / overwrite | `file_tools.py:76`                            | `{relative_path}` under project root                                  |
| Regex / literal content replace   | `file_tools.py:159-222`                       | as above (via `EditedFileContext`, `tools_base.py:406-446`)           |
| Line-addressed edits              | `file_tools.py:224-306`                       | as above                                                              |
| Auto-created project gitignore    | `project.py:304-306`                          | `.serena/.gitignore`                                                  |
| Language-server cache save        | `ls_manager.py:243-249`                       | `.serena/{CACHE_FOLDER_NAME}/{lang}/`                                 |
| Log file                          | `cli.py:331`                                  | `~/.serena/logs/…`                                                    |
| Config save                       | `config/serena_config.py` (via `save_yaml()`) | `~/.serena/serena_config.yml`                                         |
| Hook state                        | `hooks.py:178`                                | `~/.serena/hook_data/{session_id}/`                                   |


All writes are ordinary `open("w")` / `pathlib.unlink()` / `shutil.move()` — observable from outside the process only by tailing the files or polling directory state.

## 7. Read / query paths end-to-end

### `find_symbol`

1. MCP invocation → `mcp.py:176-247` wraps `FindSymbolTool.apply`.
2. `Tool.apply_ex()` (`tools_base.py:307-399`) calls the typed `apply_fn(**kwargs)` at `tools_base.py:352`.
3. `FindSymbolTool.apply()` (`symbol_tools.py:132-237`) obtains a `LanguageServerSymbolRetriever` via `create_language_server_symbol_retriever()` (`tools_base.py:51-55`).
4. The retriever calls `SolidLanguageServer.request_document_symbols()` / `workspace_symbol()`.
5. LSP cache checked first: `.serena/{CACHE_FOLDER_NAME}/{lang}/` — cache miss → forward `textDocument/documentSymbol` or `workspace/symbol` to the language server process.
6. Results shaped into `LanguageServerSymbol` dicts (`symbol_tools.py:106-118`), grouped by kind, returned as JSON.
7. After execution: `save_all_caches()` (`tools_base.py:383-388`).

### `read_file`

Tool → `project.validate_relative_path` → `project.read_file` → slice by `start_line`/`end_line` → length-limit (`file_tools.py:20-48`, `tools_base._limit_length`).

### `replace_content`

Tool → `EditedFileContext` (`tools_base.py:406-446`) → `ContentReplacer.replace` (`serena/src/serena/util/text_utils.py`) → write via the code editor on `__exit__`. Symbolic edits invalidate the LSP cache implicitly.

## 8. File-watching / LSP-event observability — nuanced

This is the single most operationally important question for Engram's anchor store, and the answer needs precision.

### What Serena does NOT do

- Serena does **not** run a filesystem watcher. `rg "watchdog|FileSystemEventHandler" serena/src/` returns zero matches in application code.
- Serena does **not** emit any external event stream (no pubsub, no hook bus) that a third process could subscribe to.
- Serena offers `restart_language_server` (`symbol_tools.py:21`) with the explicit docstring note "may be necessary when edits not through Serena happen" — i.e., the project acknowledges that external edits are invisible until the agent asks Serena to refresh.

### What Serena DOES have, but behind tool calls

Serena bundles an LSP protocol client in `serena/src/solidlsp/lsp_protocol_handler/lsp_requests.py`. That client *can* send, to the language-server process:

- `textDocument/didChange` (`lsp_requests.py:523`)
- `workspace/didChangeWatchedFiles` (`lsp_requests.py:552`)
- `workspace/didRenameFiles` (`lsp_requests.py:453`)
- `workspace/didChangeConfiguration` (`lsp_requests.py:505`)
- `workspace/didChangeWorkspaceFolders` (`lsp_requests.py:431`)

These are **outbound notifications from Serena to the LSP server** — they are how Serena tells the language server "I just edited a file" after one of its own edit tools runs. They are not inbound events from the language server to Serena, and they are not observable to any external process.

### Implication for Engram

Engram's anchor store (doc 05) cannot subscribe to Serena events because Serena emits none externally. Three viable paths for keeping symbol-to-anchor mappings fresh:

1. **Engram is the tool caller.** When Engram invokes a Serena write tool (`rename_symbol`, `replace_symbol_body`, `create_text_file`, etc.), Engram already knows a write is happening and can update its anchor store *itself*, before or after the MCP response. This is the cheapest and most reliable path and is the default assumption in doc 05.
2. **Polling.** For files that change outside Engram's control (developer saves in their IDE), Engram must either (a) call `find_symbol` periodically and diff results, or (b) install its own filesystem watcher at a layer *above* Serena. No Serena-side hook avoids this.
3. **Wrap Serena.** A small upstream PR could add an `on_tool_invoked` callback to `Tool.apply_ex` (`tools_base.py:307-399`) that Engram subscribes to. Cheap and additive. Logged as PR candidate PR-SER-1 in doc 10.

No Engram feature that requires "observe all symbol changes regardless of source" is feasible with the current Serena surface without path (2) polling.

## 9. Failure modes

- **Language server crashes / hangs.** `tools_base.py:353-366` catches `SolidLSPException.is_language_server_terminated()` and auto-restarts + retries once. If the affected language is unknown, re-raises.
- **Tool timeout.** `tools_base.py:392-399` runs each tool with `agent.serena_config.tool_timeout` (default 240s — `config/serena_config.py:47`); on timeout, returns a formatted `"Error: TimeoutError - ..."` string.
- **No active project.** `tools_base.py:338-343` returns an error listing registered projects.
- **Cache save failure.** Logged but non-fatal (`tools_base.py:383-388`).
- **Memory read of missing file.** Friendly message, no crash (`project.py:120-126`).
- **File I/O errors.** Raised, caught in `apply_ex()` (`tools_base.py:373-378`), returned as error strings.
- **Repo churn during indexing.** `cli.py:773-814` — if a file disappears mid-iteration, logged and skipped; failed files surfaced in `indexing.txt`.

Net: Serena favors **log-and-continue** over crash, and recovers LSP crashes silently within a single retry. Engram can treat Serena tool calls as best-effort idempotent.

## 10. Licensing & dependency weight

- **MIT** (`serena/LICENSE:1-22`, copyright Oraios AI 2025).
- **Python** ≥ 3.11, < 3.15 (`pyproject.toml:12`).
- **~28 direct runtime deps** (`pyproject.toml:19-56`), notables:
  - `mcp==1.27.0` — Model Context Protocol.
  - `pyright==1.1.403`, `fortls==3.2.2` — bundled language servers.
  - `pydantic==2.12.5`, `pyyaml==6.0.2`, `jinja2==3.1.6`, `flask==3.1.3`.
  - `anthropic==0.59.0`, optional `agno==2.5.10`, `google-genai==1.27.0`.
- **Transitive security pins** (`pyproject.toml:46-55`) — `urllib3`, `werkzeug`, `starlette`, `filelock`, `cryptography`, `regex`.
- **No GPL / AGPL** observed in the pinned direct or flagged transitive set. `uv.lock` present.
- **Bundled language servers** — each has its own license (e.g., pyright is MIT via npm). Not a concern for Engram's own license but worth noting for re-distribution.

## 11. Configuration schema — for Engram config reuse

`SerenaConfig` (`config/serena_config.py:200-400`, dataclass) exposes fields Engram should not duplicate but can surface to users:

- `language_backend` (LSP | JetBrains)
- `default_modes: list[str]`
- `web_dashboard: bool`, `web_dashboard_open_on_launch: bool`, `gui_log_window: bool`
- `log_level: int`, `tool_timeout: float`
- `trace_lsp_communication: bool`
- `ignored_paths: list[str]`, `read_only_memory_patterns`, `ignored_memory_patterns`
- `line_ending: LineEnding`
- `registered_projects: list[RegisteredProject]`

`Project` (per-project YAML) adds: `project_name`, `languages`, `ignored_paths`, `non_code_file_patterns`, `ignore_all_files_in_gitignore`, `line_ending`, and memory-pattern overrides.

## 12. Implications for Engram (feeds into docs 04 & 08)

- Serena is the clear "symbol" primitive. Its MCP surface is rich enough that Engram's `code.`* namespace can be mostly proxy pass-through (see doc 07). No fundamental primitive for symbol understanding is missing.
- **Serena does not observe external edits.** Any Engram feature that requires "know when any file changes" must own the watcher itself — Serena will not tell it. This forces a direct filesystem watcher in Engram OR acceptance that anchor freshness is bounded by the polling interval.
- **Memory tools overlap with MemPalace.** Serena's `write_memory`/`read_memory`/`list_memories` write markdown to `.serena/memories/`; MemPalace owns a richer, structured memory store. Doc 07 must resolve this collision (proposal: route Engram's `mem.`* namespace to MemPalace and leave Serena's memory tools alone as a legacy surface).
- **Rename propagation is feasible but not free.** Serena's `rename_symbol` is an LSP-backed atomic rename. Engram can intercept the Engram-side tool call, update its `symbol↔memory` and `symbol↔chunk` anchors, then let Serena perform the rename. Changes happening *outside* Engram (developer keypress in their IDE) are invisible and require polling or filesystem-watch reconciliation.
- **No risk of forked versions.** Serena's tool subclass registry raises `ValueError` on duplicate names (`tools_base.py:485-486`) — Engram extending Serena in-process must avoid registering duplicate tool class names.

## Assumptions

- The JetBrains tool surface count (≈10) is an estimate based on the observed file; exact count depends on which markers are active at runtime. Not load-bearing for any design decision in later docs.
- The precise LSP cache backing store (SQLite vs. JSON per language) was not inspected — `ls_manager.save_all_caches()` is cited but its implementation in `solidlsp/` was not opened. Doc 05 does not depend on this detail.
- Bundled language-server license claims are restated from package metadata, not verified per-package. Not load-bearing for Engram's MIT surface.


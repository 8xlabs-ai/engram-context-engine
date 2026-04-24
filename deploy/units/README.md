# OS-level supervisor units

Engram's `Supervisor` class (in `engram.upstream.supervisor`) already manages
the three upstream MCP subprocesses inside a running `engram mcp` process and
transparently reconnects any that drop via the built-in watchdog. These OS
units are optional — use them only if you want upstream processes to stay warm
between `engram mcp` invocations.

- `ai.engram.plist` — user-level launchd plist for macOS. Install with:
  ```
  cp deploy/units/ai.engram.plist ~/Library/LaunchAgents/
  launchctl load ~/Library/LaunchAgents/ai.engram.plist
  ```

- `engram.service` — systemd user unit for Linux. Install with:
  ```
  mkdir -p ~/.config/systemd/user
  cp deploy/units/engram.service ~/.config/systemd/user/
  systemctl --user daemon-reload
  systemctl --user enable --now engram.service
  ```

Both units run `engram mcp` with `ENGRAM_WORKSPACE` set to a workspace path
you must edit before installing.

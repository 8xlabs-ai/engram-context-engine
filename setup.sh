#!/usr/bin/env bash
# Engram one-shot installer + workspace bootstrapper.
#
# What it does (idempotent — safe to re-run):
#   1. Verifies python (>=3.11,<3.15), node (>=20,<24), docker on PATH.
#   2. Creates a venv at ./.venv if absent.
#   3. pip-installs the engram package in editable mode + dev extras.
#   4. (optional) npm-installs claude-context-mcp globally; skip with --skip-npm.
#   5. (optional) brings up the Milvus + Ollama compose stack; skip with --skip-compose.
#   6. Pulls the nomic-embed-text Ollama model if absent.
#   7. Runs `engram init` against --workspace (default: $PWD).
#   8. Patches .engram/config.yaml with absolute venv paths + serena --project flag.
#   9. Runs `engram smoke-test` to confirm all three upstreams probe ok.
#
# Usage:
#   ./setup.sh [--workspace DIR] [--skip-compose] [--skip-npm] [--force-init] [--no-smoke]
#
# Exit codes:
#   0  success
#   1  unmet prerequisite
#   2  install step failed
#   3  smoke-test failed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$PWD"
SKIP_COMPOSE=0
SKIP_NPM=0
FORCE_INIT=0
NO_SMOKE=0

usage() {
  sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace) WORKSPACE="$2"; shift 2 ;;
    --skip-compose) SKIP_COMPOSE=1; shift ;;
    --skip-npm) SKIP_NPM=1; shift ;;
    --force-init) FORCE_INIT=1; shift ;;
    --no-smoke) NO_SMOKE=1; shift ;;
    -h|--help) usage ;;
    *) echo "unknown flag: $1" >&2; exit 1 ;;
  esac
done

WORKSPACE="$(cd "$WORKSPACE" && pwd)"

step()  { printf '\033[1;34m▶\033[0m  %s\n' "$*"; }
ok()    { printf '\033[1;32m✓\033[0m  %s\n' "$*"; }
warn()  { printf '\033[1;33m!\033[0m  %s\n' "$*" >&2; }
fail()  { printf '\033[1;31m✗\033[0m  %s\n' "$*" >&2; exit "${2:-2}"; }

# ---------------------------------------------------------------------------
# 1. Prerequisites
# ---------------------------------------------------------------------------
step "checking prerequisites"

PYTHON_BIN=""
for cand in python3.13 python3.12 python3.11 python3.14 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    ver="$("$cand" -c 'import sys;print("{}.{}".format(sys.version_info.major, sys.version_info.minor))')"
    major="${ver%.*}"; minor="${ver#*.}"
    if [[ "$major" -eq 3 && "$minor" -ge 11 && "$minor" -lt 15 ]]; then
      PYTHON_BIN="$(command -v "$cand")"
      ok "python $ver at $PYTHON_BIN"
      break
    fi
  fi
done
[[ -n "$PYTHON_BIN" ]] || fail "Python >=3.11,<3.15 not found on PATH" 1

if [[ "$SKIP_NPM" -eq 0 || "$SKIP_COMPOSE" -eq 0 ]]; then
  if command -v node >/dev/null 2>&1; then
    nv="$(node --version | sed 's/^v//')"
    nmajor="${nv%%.*}"
    if [[ "$nmajor" -ge 20 && "$nmajor" -lt 24 ]]; then
      ok "node v$nv"
    else
      fail "Node >=20,<24 required, found v$nv" 1
    fi
  else
    fail "node not on PATH (required for claude-context-mcp)" 1
  fi
fi

if [[ "$SKIP_COMPOSE" -eq 0 ]]; then
  command -v docker >/dev/null 2>&1 || fail "docker not on PATH" 1
  docker compose version >/dev/null 2>&1 || fail "'docker compose' subcommand missing" 1
  ok "docker $(docker --version | awk '{print $3}' | tr -d ',')"
fi

# ---------------------------------------------------------------------------
# 2. Virtualenv
# ---------------------------------------------------------------------------
VENV="$SCRIPT_DIR/.venv"
if [[ ! -x "$VENV/bin/python" ]]; then
  step "creating virtualenv at $VENV"
  "$PYTHON_BIN" -m venv "$VENV"
  ok "venv ready"
else
  ok "venv exists at $VENV"
fi
PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"

# ---------------------------------------------------------------------------
# 3. pip install
# ---------------------------------------------------------------------------
step "installing engram + dev extras (editable)"
"$PIP" install --quiet --upgrade pip wheel >/dev/null
"$PIP" install --quiet -e "$SCRIPT_DIR[dev]" || fail "pip install failed"
ok "engram installed in venv"

# ---------------------------------------------------------------------------
# 4. claude-context-mcp (optional)
# ---------------------------------------------------------------------------
if [[ "$SKIP_NPM" -eq 0 ]]; then
  if npm list -g --depth=0 2>/dev/null | grep -q "@zilliz/claude-context-mcp"; then
    ok "@zilliz/claude-context-mcp already installed"
  else
    step "installing @zilliz/claude-context-mcp@0.1.8 globally"
    npm install -g @zilliz/claude-context-mcp@0.1.8 >/dev/null \
      || warn "global npm install failed; npx will pull lazily"
    ok "claude-context-mcp ready (or will be via npx)"
  fi
else
  ok "skipping npm (--skip-npm)"
fi

# ---------------------------------------------------------------------------
# 5. Compose stack
# ---------------------------------------------------------------------------
if [[ "$SKIP_COMPOSE" -eq 0 ]]; then
  step "bringing up Milvus + Ollama compose stack"
  ( cd "$SCRIPT_DIR" && docker compose -f deploy/compose.yaml up -d ) \
    || fail "docker compose up failed"

  step "waiting for milvus-standalone healthy (up to 120s)"
  for _ in $(seq 1 24); do
    s="$(docker inspect -f '{{.State.Health.Status}}' deploy-milvus-standalone-1 2>/dev/null || echo missing)"
    if [[ "$s" == "healthy" ]]; then
      ok "milvus healthy"
      break
    fi
    sleep 5
  done
  [[ "$s" == "healthy" ]] || fail "milvus did not reach healthy state"

  step "ensuring ollama has nomic-embed-text"
  if docker exec deploy-ollama-1 ollama list 2>/dev/null | grep -q "nomic-embed-text"; then
    ok "ollama model present"
  else
    docker exec deploy-ollama-1 ollama pull nomic-embed-text >/dev/null \
      || fail "ollama pull failed"
    ok "nomic-embed-text pulled"
  fi
else
  ok "skipping compose (--skip-compose)"
fi

# ---------------------------------------------------------------------------
# 6. engram init
# ---------------------------------------------------------------------------
CONFIG="$WORKSPACE/.engram/config.yaml"
init_args=("--workspace" "$WORKSPACE" "--embedding-provider" "Ollama" "--skip-prereq-check")
if [[ "$FORCE_INIT" -eq 1 ]]; then
  init_args+=("--force")
fi

if [[ -f "$CONFIG" && "$FORCE_INIT" -eq 0 ]]; then
  ok "$CONFIG already exists (pass --force-init to rewrite)"
else
  step "engram init --workspace $WORKSPACE"
  "$PYTHON" -m engram init "${init_args[@]}" >/dev/null \
    || fail "engram init failed"
  ok "workspace initialized at $WORKSPACE/.engram/"
fi

# ---------------------------------------------------------------------------
# 7. Patch config (absolute venv paths + serena --project)
# ---------------------------------------------------------------------------
step "patching $CONFIG (absolute paths + serena --project)"
"$PYTHON" - <<PY
import sys, yaml, pathlib
cfg_path = pathlib.Path("$CONFIG")
venv_bin = pathlib.Path("$VENV/bin")
workspace = "$WORKSPACE"

cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
serena_cmd = [str(venv_bin / "serena"), "start-mcp-server", "--project", workspace]
mempalace_cmd = [str(venv_bin / "mempalace-mcp")]

if cfg["upstreams"]["serena"]["command"] != serena_cmd:
    cfg["upstreams"]["serena"]["command"] = serena_cmd
if cfg["upstreams"]["mempalace"]["command"] != mempalace_cmd:
    cfg["upstreams"]["mempalace"]["command"] = mempalace_cmd

cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
PY
ok "config patched"

# ---------------------------------------------------------------------------
# 8. Smoke test
# ---------------------------------------------------------------------------
if [[ "$NO_SMOKE" -eq 1 ]]; then
  ok "skipping smoke-test (--no-smoke)"
else
  step "engram smoke-test (this loads MemPalace Chroma; ~10s on first run)"
  smoke_args=("--workspace" "$WORKSPACE")
  if [[ "$SKIP_COMPOSE" -eq 1 ]]; then
    smoke_args+=("--skip-upstreams")
  fi
  if "$PYTHON" -m engram smoke-test "${smoke_args[@]}"; then
    ok "smoke-test green"
  else
    fail "smoke-test failed — run \`$PYTHON -m engram status --workspace $WORKSPACE\` to debug" 3
  fi
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
cat <<EOF

\033[1;32mEngram is ready.\033[0m

  workspace:  $WORKSPACE
  config:     $CONFIG
  venv:       $VENV
  engram-mcp: $VENV/bin/engram-mcp

Next:
  • Register with your MCP client (see README §7).
    Quick wire-up for Claude Code:
      claude mcp add engram \\
        --scope user \\
        --env ENGRAM_WORKSPACE=$WORKSPACE \\
        -- $VENV/bin/engram-mcp

  • Inspect tools:
      $PYTHON -m engram status --workspace $WORKSPACE

  • Tear down compose later with:
      docker compose -f $SCRIPT_DIR/deploy/compose.yaml down

EOF

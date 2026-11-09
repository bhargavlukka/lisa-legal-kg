#!/usr/bin/env bash
# One command to bring LISA up for a live demo (macOS):
#   scripts/demo.sh
# Starts Docker Desktop if needed, the Docker stack (Neo4j, Jaeger, four MCP servers), the web UI on :8200
# (only if nothing is listening there yet), then opens http://127.0.0.1:8200. Safe to run again at any time.
# Stop everything with scripts/demo_stop.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
UI_PORT=8200
UI_URL="http://127.0.0.1:${UI_PORT}"
LOG="$ROOT/out/web.log"
PIDFILE="$ROOT/out/web.pid"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '    \033[32mok\033[0m  %s\n' "$*"; }
die()  { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
listening() { nc -z 127.0.0.1 "$1" >/dev/null 2>&1; }
wait_port() {  # wait_port PORT NAME SECONDS
  local i
  for ((i = 0; i < $3; i++)); do
    if listening "$1"; then ok "$2 (port $1)"; return 0; fi
    sleep 1
  done
  die "$2 did not come up on port $1 within $3 s. Check: docker compose --env-file .env logs --tail 50"
}

[[ -f .env ]] || die ".env not found in $ROOT (it holds LISA_DATA_DIR and the secrets)."
# .env has a quoted path with spaces/parentheses: source it with the shell, never word-split it
set -a; . ./.env; set +a
[[ -d "${LISA_DATA_DIR:-}" ]] || die "LISA_DATA_DIR in .env does not point to a folder: ${LISA_DATA_DIR:-<unset>}"
[[ -n "${COURTLISTENER_TOKEN:-}" ]] || say "Note: COURTLISTENER_TOKEN is empty - external CourtListener lookups will be skipped (answers still work from the corpus)."

# 1. Docker
say "Checking Docker"
if ! docker info >/dev/null 2>&1; then
  say "Docker is not running - starting Docker Desktop (this can take a minute)"
  open -a Docker || die "Could not start Docker Desktop. Start it by hand and re-run."
  for ((i = 0; i < 120; i++)); do docker info >/dev/null 2>&1 && break; sleep 2; done
  docker info >/dev/null 2>&1 || die "Docker did not become ready in 4 minutes."
fi
ok "Docker is running"

# 2. Stack
say "Starting the Docker stack (Neo4j, Jaeger, four MCP servers)"
docker compose --env-file .env up -d
say "Waiting for services"
wait_port 7474 "Neo4j browser" 120
wait_port 7687 "Neo4j bolt" 120
wait_port 16686 "Jaeger" 60
wait_port 8101 "Graph server" 90
wait_port 8102 "Citation verifier" 90
wait_port 8103 "Analytics server" 90
wait_port 8104 "External law server" 90

# 3. Web UI (only one instance)
say "Web UI"
if listening "$UI_PORT"; then
  ok "already running on port $UI_PORT - leaving it as is"
else
  PY="$ROOT/.venv/bin/python"; [[ -x "$PY" ]] || PY="$(command -v python3)"
  mkdir -p "$ROOT/out"
  nohup "$PY" scripts/web.py >>"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
  wait_port "$UI_PORT" "LISA web UI (log: out/web.log)" 60
fi

# 4. Open the page
say "Opening $UI_URL"
open "$UI_URL"
cat <<MSG

LISA is ready.
  Web UI          $UI_URL
  Neo4j browser   http://127.0.0.1:7474   (user neo4j, password = NEO4J_PASSWORD in .env)
  Jaeger traces   http://127.0.0.1:16686
Stop everything:  scripts/demo_stop.sh
MSG

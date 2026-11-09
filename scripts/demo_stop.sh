#!/usr/bin/env bash
# Stop the LISA demo: the web UI on :8200 and the Docker stack (data volumes are kept - no -v).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
UI_PORT=8200

echo "==> Stopping the web UI"
PIDS="$(lsof -nP -tiTCP:${UI_PORT} -sTCP:LISTEN 2>/dev/null || true)"
if [[ -n "$PIDS" ]]; then
  kill $PIDS 2>/dev/null || true
  for i in 1 2 3 4 5; do lsof -nP -tiTCP:${UI_PORT} -sTCP:LISTEN >/dev/null 2>&1 || break; sleep 1; done
  lsof -nP -tiTCP:${UI_PORT} -sTCP:LISTEN >/dev/null 2>&1 && kill -9 $PIDS 2>/dev/null
  echo "    stopped (pid $PIDS)"
else
  echo "    not running"
fi
rm -f "$ROOT/out/web.pid"

echo "==> Stopping the Docker stack"
if docker info >/dev/null 2>&1; then
  set -a; . ./.env; set +a
  docker compose --env-file .env down
else
  echo "    Docker is not running - nothing to stop"
fi
echo "Done."

#!/bin/sh
set -eu

: "${CONTROL_PLANE_API_KEY:?set CONTROL_PLANE_API_KEY}"
: "${TUNNEL_ID:?set TUNNEL_ID}"

export MCP_ROOT="${MCP_ROOT:-/workspace}"
export HOME="${HOME:-/tmp}"
export MCP_HTTP_HOST="${MCP_HTTP_HOST:-127.0.0.1}"
export MCP_HTTP_PORT="${MCP_HTTP_PORT:-8000}"
export MCP_HTTP_PATH="${MCP_HTTP_PATH:-/mcp}"

mkdir -p "$HOME/.config"

mcp_pid=""
tunnel_pid=""

cleanup() {
  if [ -n "$tunnel_pid" ]; then
    kill "$tunnel_pid" 2>/dev/null || true
  fi
  if [ -n "$mcp_pid" ]; then
    kill "$mcp_pid" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
}

trap cleanup INT TERM EXIT

python /app/server.py &
mcp_pid="$!"

python - <<PY
import time
import urllib.request

url = "http://127.0.0.1:${MCP_HTTP_PORT}/healthz"
last_error = None

for _ in range(50):
  try:
    with urllib.request.urlopen(url, timeout=1) as response:
      if response.status == 200:
        raise SystemExit(0)
  except Exception as exc:
    last_error = exc
    time.sleep(0.1)

raise SystemExit(f"MCP server did not become ready: {last_error}")
PY

tunnel-client run \
  --control-plane.tunnel-id "$TUNNEL_ID" \
  --control-plane.api-key "env:CONTROL_PLANE_API_KEY" \
  --mcp.server-url "http://127.0.0.1:${MCP_HTTP_PORT}${MCP_HTTP_PATH}" &
tunnel_pid="$!"

wait "$tunnel_pid"

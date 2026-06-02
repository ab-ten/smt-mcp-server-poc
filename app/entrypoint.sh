#!/bin/sh
set -eux

: "${CONTROL_PLANE_API_KEY:?set CONTROL_PLANE_API_KEY}"
: "${TUNNEL_ID:?set TUNNEL_ID}"

export MCP_ROOT="${MCP_ROOT:-/workspace}"
export HOME="${HOME:-/tmp}"

mkdir -p "$HOME/.config"

tunnel-client init \
  --sample sample_mcp_stdio_local \
  --profile local-files \
  --tunnel-id "$TUNNEL_ID" \
  --mcp-command "python /app/server.py"

exec tunnel-client run --profile local-files

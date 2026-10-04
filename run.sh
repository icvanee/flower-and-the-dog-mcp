#!/usr/bin/env bash
# Start de MCP-server met de secrets uit het lokale env-bestand (zie env.example).
# Staan er op://-verwijzingen in, dan lost `op run` die op via 1Password.
set -euo pipefail
cd "$(dirname "$0")"

env_file="${MCP_ENV_FILE:-$HOME/.config/flower-and-the-dog-mcp/env}"
[ -f "$env_file" ] || { echo "env-bestand ontbreekt: $env_file (zie env.example)" >&2; exit 1; }

if grep -q 'op://' "$env_file"; then
  # Alleen-lezen-token voor de kluis "Mac Mini" (mac-mini-setup: bin/op-token.sh)
  if [ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
    OP_SERVICE_ACCOUNT_TOKEN=$(security find-generic-password -s op-sa-macmini -w) \
      || { echo "geen 1Password-token in de Keychain (op-sa-macmini)" >&2; exit 1; }
    export OP_SERVICE_ACCOUNT_TOKEN
  fi
  exec op run --env-file="$env_file" -- uv run --locked server.py
fi
set -a; . "$env_file"; set +a
exec uv run --locked server.py

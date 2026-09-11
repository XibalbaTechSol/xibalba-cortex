#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/xibalba-cortex"
ENV_FILE="$CONFIG_DIR/core-sync.env"
INSTALLER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install_core_sync.sh"

mkdir -p "$CONFIG_DIR"
read -r -p "CORE oracle URL [http://127.0.0.1:8080]: " core_url
core_url="${core_url:-http://127.0.0.1:8080}"
read -r -p "Cortex account UUID: " account_id
read -r -p "Bound controller EVM address (0x...): " controller

[[ "$core_url" =~ ^https?://[^[:space:]]+$ ]] || { echo "ERROR: invalid CORE URL" >&2; exit 1; }
[[ "$account_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$ ]] || { echo "ERROR: account ID must be a UUID" >&2; exit 1; }
[[ "$controller" =~ ^0x[0-9a-fA-F]{40}$ ]] || { echo "ERROR: controller must be a 20-byte EVM address" >&2; exit 1; }

umask 077
cat > "$ENV_FILE" <<EOF
XIBALBA_CORE_ORACLE_URL=$core_url
XIBALBA_CORTEX_HOME=%h/.hermes/xibalba-cortex
XIBALBA_CORTEX_ACCOUNT_ID=$account_id
XIBALBA_CORTEX_CONTROLLER=${controller,,}
EOF
chmod 600 "$ENV_FILE"
exec bash "$INSTALLER"

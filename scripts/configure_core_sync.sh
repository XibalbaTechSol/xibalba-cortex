#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/xibalba-cortex"
ENV_FILE="$CONFIG_DIR/core-sync.env"
INSTALLER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install_core_sync.sh"
CORTEX_HOME="${XIBALBA_CORTEX_HOME:-$HOME/.hermes/xibalba-cortex}"
[[ "$CORTEX_HOME" == %h/* ]] && CORTEX_HOME="$HOME/${CORTEX_HOME#%h/}"
ACCOUNT_DB="$CORTEX_HOME/ingest_tokens.sqlite3"

mkdir -p "$CONFIG_DIR"
read -r -p "CORE oracle URL [http://127.0.0.1:8080]: " core_url
core_url="${core_url:-http://127.0.0.1:8080}"
account_id="${XIBALBA_CORTEX_ACCOUNT_ID:-}"
controller="${XIBALBA_CORTEX_CONTROLLER:-}"

# Prefer the live local account binding. Never infer a controller from wallets,
# transactions, or test fixtures; it must be stored on the selected account.
if [[ -z "$account_id" && -r "$ACCOUNT_DB" ]]; then
  mapfile -t accounts < <(python3 - "$ACCOUNT_DB" <<'PY'
import sqlite3, sys
db = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True)
for row in db.execute("SELECT id,email,controller_address FROM accounts WHERE status='active' ORDER BY created_at"):
    print("\t".join("" if v is None else str(v) for v in row))
PY
  )
  if [[ -n "${XIBALBA_CORTEX_ACCOUNT_EMAIL:-}" ]]; then
    for row in "${accounts[@]}"; do
      IFS=$'\t' read -r candidate_id candidate_email candidate_controller <<< "$row"
      if [[ "$candidate_email" == "$XIBALBA_CORTEX_ACCOUNT_EMAIL" ]]; then
        account_id="$candidate_id"; controller="$candidate_controller"; break
      fi
    done
  elif [[ "${#accounts[@]}" -eq 1 ]]; then
    IFS=$'\t' read -r account_id _ controller <<< "${accounts[0]}"
  elif [[ "${#accounts[@]}" -gt 1 ]]; then
    echo "Multiple active Cortex accounts found; choose by email:" >&2
    for row in "${accounts[@]}"; do
      IFS=$'\t' read -r _ candidate_email _ <<< "$row"
      echo "  $candidate_email" >&2
    done
    read -r -p "Cortex account email: " selected_email
    for row in "${accounts[@]}"; do
      IFS=$'\t' read -r candidate_id candidate_email candidate_controller <<< "$row"
      if [[ "$candidate_email" == "$selected_email" ]]; then
        account_id="$candidate_id"; controller="$candidate_controller"; break
      fi
    done
  fi
fi

if [[ -z "$account_id" ]]; then
  read -r -p "Cortex account UUID (or set XIBALBA_CORTEX_ACCOUNT_EMAIL): " account_id
fi
if [[ -z "$controller" ]]; then
  mapfile -t controllers < <(python3 - "$core_url" <<'PY'
import json, sys
from urllib.request import urlopen
try:
    with urlopen(sys.argv[1].rstrip('/') + '/v1/agents/snapshot', timeout=5) as response:
        payload = json.load(response)
    values = sorted({str(row.get('controller','')).lower() for row in payload.get('agents', [])
                     if isinstance(row, dict) and str(row.get('controller','')).startswith('0x')})
    for value in values:
        if len(value) == 42:
            print(value)
except Exception:
    pass
PY
  )
  if [[ "${#controllers[@]}" -eq 1 ]]; then
    controller="${controllers[0]}"
    echo "Using the only controller found in the CORE snapshot: $controller"
  else
    if [[ "${#controllers[@]}" -gt 1 ]]; then
      echo "Multiple CORE controllers found; choose the one bound to this Cortex account:" >&2
      printf '  %s\n' "${controllers[@]}" >&2
    fi
    read -r -p "Bound controller EVM address (0x...): " controller
  fi
fi

[[ "$core_url" =~ ^https?://[^[:space:]]+$ ]] || { echo "ERROR: invalid CORE URL" >&2; exit 1; }
[[ "$account_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$ ]] || { echo "ERROR: account ID must be a UUID" >&2; exit 1; }
[[ "$controller" =~ ^0x[0-9a-fA-F]{40}$ ]] || { echo "ERROR: controller must be a 20-byte EVM address" >&2; exit 1; }

umask 077
cat > "$ENV_FILE" <<EOF
XIBALBA_CORE_ORACLE_URL=$core_url
XIBALBA_CORTEX_HOME=$CORTEX_HOME
XIBALBA_CORTEX_ACCOUNT_ID=$account_id
XIBALBA_CORTEX_CONTROLLER=${controller,,}
EOF
chmod 600 "$ENV_FILE"
exec bash "$INSTALLER"

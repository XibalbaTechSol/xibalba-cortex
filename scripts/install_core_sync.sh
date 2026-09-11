#!/usr/bin/env bash
set -euo pipefail

# Install and run the finalized CORE-registration reconciliation timer.
# This is a user service: it does not require sudo and never changes chain state.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
CONFIG_DIR="${XIBALBA_CORTEX_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/xibalba-cortex}"
ENV_FILE="$CONFIG_DIR/core-sync.env"

die() { echo "ERROR: $*" >&2; exit 1; }
command -v systemctl >/dev/null 2>&1 || die "systemctl is required"
[[ -f "$REPO_ROOT/packaging/systemd/xibalba-cortex-core-sync.service" ]] || die "service template missing"
[[ -f "$REPO_ROOT/packaging/systemd/xibalba-cortex-core-sync.timer" ]] || die "timer template missing"

mkdir -p "$USER_UNIT_DIR" "$CONFIG_DIR"
if [[ ! -e "$ENV_FILE" ]]; then
  install -m 0600 "$REPO_ROOT/packaging/systemd/core-sync.env.example" "$ENV_FILE"
  die "created $ENV_FILE; edit its CORE URL, Cortex account ID, and controller, then rerun"
fi

for required in XIBALBA_CORE_ORACLE_URL XIBALBA_CORTEX_HOME XIBALBA_CORTEX_ACCOUNT_ID XIBALBA_CORTEX_CONTROLLER; do
  value="$(awk -F= -v key="$required" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE")"
  [[ -n "$value" ]] || die "$required is missing from $ENV_FILE"
  case "$value" in
    *example.invalid*|replace-*|REPLACE_*|0x0000000000000000000000000000000000000000)
      die "$required still contains a placeholder in $ENV_FILE" ;;
  esac
done

install -m 0644 "$REPO_ROOT/packaging/systemd/xibalba-cortex-core-sync.service" "$USER_UNIT_DIR/xibalba-cortex-core-sync.service"
install -m 0644 "$REPO_ROOT/packaging/systemd/xibalba-cortex-core-sync.timer" "$USER_UNIT_DIR/xibalba-cortex-core-sync.timer"
systemctl --user daemon-reload
systemctl --user enable --now xibalba-cortex-core-sync.timer
systemctl --user start xibalba-cortex-core-sync.service
systemctl --user --no-pager status xibalba-cortex-core-sync.timer
echo "Cortex CORE-registration sync installed and run once; timer interval is five minutes."

#!/usr/bin/env bash
# Installs the isolated xibalba-cortex-worker Hermes profile from this repo's tracked
# scripts/worker-profile/ artifact into ~/.hermes/profiles/xibalba-cortex-worker/.
#
# Idempotent: safe to re-run after editing scripts/worker-profile/config.yaml or SOUL.md
# to push the update. Does not touch auth.json if one already exists in the profile (codex
# credentials are per-profile and not something this script can regenerate).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE_NAME="xibalba-cortex-worker"
PROFILE_HOME="${HERMES_HOME:-$HOME/.hermes}/profiles/${PROFILE_NAME}"

mkdir -p "${PROFILE_HOME}/memories" "${PROFILE_HOME}/workspace"

cp "${REPO_DIR}/scripts/worker-profile/config.yaml" "${PROFILE_HOME}/config.yaml"
cp "${REPO_DIR}/scripts/worker-profile/SOUL.md" "${PROFILE_HOME}/SOUL.md"

# Empty memory files -- this worker starts every task with no prior context.
: > "${PROFILE_HOME}/memories/MEMORY.md"
: > "${PROFILE_HOME}/memories/USER.md"

if [ ! -f "${PROFILE_HOME}/auth.json" ] && [ -f "${HERMES_HOME:-$HOME/.hermes}/auth.json" ]; then
    cp "${HERMES_HOME:-$HOME/.hermes}/auth.json" "${PROFILE_HOME}/auth.json"
    echo "Copied auth.json from the default profile -- codex credentials are per-profile."
fi

echo "Installed ${PROFILE_NAME} profile at ${PROFILE_HOME}"
echo "Verify isolation with:"
echo "  hermes -p ${PROFILE_NAME} config get memory.memory_enabled   # expect false"
echo "  hermes -p ${PROFILE_NAME} mcp list                            # expect only xibalba_cortex"

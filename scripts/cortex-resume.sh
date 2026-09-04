#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
state_file="$repo_root/docs/PROJECT_STATE.md"

if [[ ! -f "$state_file" ]]; then
  printf 'Missing canonical state: %s\n' "$state_file" >&2
  exit 1
fi

printf '%s\n' '=== Cortex canonical project state ==='
sed -n '1,220p' "$state_file"
printf '%s\n' '' '=== Live repository ==='
git -C "$repo_root" status --short
git -C "$repo_root" log -1 --oneline

printf '%s\n' '' '=== Live local readiness (profile default) ==='
cd "$repo_root"
uv run xibalba-cortex-operator production-readiness 2>/dev/null || printf '%s\n' 'Readiness command unavailable for the default profile; inspect PROJECT_STATE.md.'

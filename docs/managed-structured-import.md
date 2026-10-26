# Managed structured import

Export and upload a local Cortex workspace without flattening it into plain text:

    source /home/xibalba/.config/xibalba/cortex.env
    uv run xibalba-cortex-managed-import \
      --profile /home/xibalba/.hermes/xibalba-cortex \
      --endpoint https://cortex-managed-pilot.onrender.com

The command reads the local SQLite graph and uploads idempotent batches to
POST /api/managed/import. It preserves memory IDs and statuses, source/provenance rows,
hash-linked memory events, sessions, entities, aliases, memory/entity links, relations and
metadata nodes. Re-running the command is safe.

Use --dry-run to inspect counts without sending data, and --exclude-forgotten to omit
forgotten memories. A full import of the current Codex profile is 3,202 memories, so the
managed Pro plan is required; the Free plan caps storage at 1,000 memories.

The managed service currently stores these graph rows but its hosted read API exposes only
memory list/search. The local console's Graph and Timeline lenses remain the visualization
surface until managed graph read endpoints are enabled.

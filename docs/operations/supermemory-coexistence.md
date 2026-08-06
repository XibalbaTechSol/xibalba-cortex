# Supermemory Coexistence And Migration Gate

Status: prototype shadow period.

Xibalba Graph Memory is not a silent replacement for Supermemory yet. During the shadow period,
Supermemory remains the active automatic memory provider while this project exposes explicit MCP
tools for provenance-aware recall, graph inspection, contradiction handling, verification, and
operator-managed writes.

## Shadow Mode Rules

- Supermemory can continue serving automatic background memory.
- Xibalba Graph Memory serves explicit operator and runtime-controller calls.
- Recalled graph-memory content is evidence, not instruction authority.
- No runtime may claim graph-memory parity unless its adapter has tested session, identity,
  telemetry, and recall behavior.
- Contradictions, supersession, forgetting, and unverified Integrity links must stay visible in
  the UI and MCP results before migration.

## Migration Gate

Do not promote graph memory to the primary automatic memory provider until all gates pass:

1. `uv run pytest -q` passes on a clean install.
2. `cd viewer && npm run build` passes.
3. Isolated Hermes profile can discover `xibalba-graph-memory` and call `memory_status`,
   `memory_remember`, `memory_recall`, `memory_verify_chain`, and `memory_backup`.
4. At least one restore rehearsal has been run through `xibalba-graph-memory-operator restore`
   against a disposable profile.
5. Claude, agy, and Codex adapter capability reports are truthful and tested; missing hook
   surfaces remain explicit limitations.
6. Integrity DAG links distinguish local byte lineage from truth, authorization, completeness,
   and external anchoring.
7. Viewer shows provenance, lifecycle state, contradictions, forgetting state, event-chain
   verification, and Integrity link state without implying recalled content is trusted.

## Rollback Rule

If graph memory becomes primary later, keep Supermemory configured but disabled for one release
window. Re-enable Supermemory immediately if MCP discovery fails, recall returns empty for known
seeded facts, backup verification fails, or graph-memory storage reports anything other than
`integrity_check=ok`.

## Current Decision

Remain in coexistence/shadow mode. The prototype has local tests and explicit operator commands,
but live isolated Hermes discovery, Codex hook parity, and Integrity DAG link verification are
not fully closed.

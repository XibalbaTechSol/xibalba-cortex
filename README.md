# Xibalba Graph Memory

A local, provenance-aware graph memory Model Context Protocol server for Hermes Agent. The initial hybrid deployment keeps Supermemory active while exposing explicit local graph tools.

## 2026-08-06 audit status

The current status ledger is [`docs/audits/2026-08-06-status.md`](docs/audits/2026-08-06-status.md), and the consolidated cross-repository implementation plan is `/home/xibalba/Documents/INTEGRITY — Cross-Repository Audit and Implementation Plan.md`.

The local worktree contains uncommitted runtime adapters, controller/session synchronization, tests, and a viewer. `uv sync --extra drive && uv run pytest -q` passed. Plain `uv sync && uv run pytest -q` failed during collection because Drive tests import optional Google dependencies without the Drive extra. This repository is a local prototype, not production-certified.

Normative behavior is defined by [`spec/xibalba-graph-memory-v1.md`](spec/xibalba-graph-memory-v1.md), with this repository entry-point specification in [`SPECIFICATION.md`](SPECIFICATION.md). Historical plans are archived under [`docs/archive/2026-08-06`](docs/archive/2026-08-06); they do not override the normative specification or current audit ledger.

# Hybrid Extraction/Retrieval Hardening — Handoff

**Written:** 2026-08-13
**Plan file this work executes:** `~/.claude/plans/for-the-requested-feature-compiled-pine.md`
**Status:** Phases A and B complete and live-verified. Phase C (items 5-8) not started.

## What this covers

The user's status report split remaining work into 4 "critical blocker" items and 4 "important
but secondary" items, building on the checkpoint recorded in `spec/latest-hybrid-extraction.md`
(commit `96d0d0e`, 2026-08-13): a direct Hermes `-z` invocation produced schema-valid entity JSON
but leaked unrelated recalled context into evidence quotes, which the quote-containment validator
correctly rejected (fail-closed) but which exposed that the worker path wasn't actually isolated.

This handoff picks up from there. Read `spec/latest-hybrid-extraction.md` in full for the
authoritative, chronological record — this document is a navigational summary, not a
replacement for it.

## Done: Phase A — isolated worker path + extraction proposal lifecycle (items 1+2)

- **Isolated Hermes worker profile** at `~/.hermes/profiles/xibalba-cortex-worker/`, installed
  from the repo-tracked `scripts/worker-profile/{config.yaml,SOUL.md}` via
  `scripts/setup-cortex-worker-profile.sh` (idempotent — re-run after editing the tracked
  artifact to push updates). The profile's `config.yaml` is self-sufficient (a profile config is
  a full replacement of the default, not an overlay), restricts `mcp_servers.xibalba_cortex` to
  an explicit 4-tool allowlist (`tools.include`, not the bare server — the bare server would
  expose ~60 tools including `memory_recall`/`memory_hybrid_retrieve`), sets
  `memory.memory_enabled: false`/`user_profile_enabled: false`, and omits `plugins` entirely.
  `NativeHarnessInferenceProvider` (`providers.py`) gained a `profile_name` field that appends
  `-p <profile>` to the constructed `hermes -z ...` command.
- **Live-verified, not just configured**: `hermes -p xibalba-cortex-worker mcp list` shows
  exactly 4 tools selected; a leak-probe prompt ("list every memory/context document you were
  given") returned `[]`; a real (unmocked) extraction run against a narrow, distinctive test
  memory produced evidence quotes that were all verbatim substrings of that memory only. All
  three transcripts are recorded in `spec/latest-hybrid-extraction.md`.
- **`memory_evidence_bundle` MCP tool** (`server.py`) resolves a task's own `evidence_scope`
  contract into a bounded evidence bundle via `GraphStore.fetch_bounded_evidence` (this store
  method already existed from the prior commit; it just had no MCP tool wired to it).
- **`extraction_proposals` table** (schema v8) generalizes the existing `para_classifications`
  pattern to `extract_entities`/`extract_relations`: one row per extracted item,
  `proposed`/`accepted`/`dismissed`/`stale` states, `decide_extraction_proposal` rejects
  acceptance when the source memory's `content_hash` has diverged (→ `stale`), and acceptance
  never mutates the source memory row — only inserts new derived entity/relation records.
  `para_classifications` was deliberately left alone (works, tested, has UI already).
- **Validation moved server-side**: `validate_extraction_result` moved from `hermes_worker.py`
  to `providers.py` (breaks an import cycle — `store.py` can now call it) and now runs *inside*
  `complete_inference_task` itself, gating completion regardless of caller. This matters because
  the isolated worker calls `memory_complete_inference_task` directly over MCP — if validation
  only ran in the old in-process Python caller, an external caller's invalid output would have
  silently completed the task instead of failing closed.

Tests: `tests/test_extraction_proposals.py`, `tests/test_hermes_worker_isolation.py`, plus an
MCP round-trip test added to `tests/test_server.py`.

## Done: Phase B — retrieval trace + projection checkpoint/reconciliation (items 3+4)

- **Fixed a real correctness bug first**: `events.py`'s `merkle_root`/`merkle_parent` hashed
  only leaf values (no domain tag in the preimage — a projection root and a trace root over
  identical leaves would have been byte-identical) and sorted each pair's children (a full
  leaf-set reordering was undetectable from the root alone, which would have defeated "verify
  rebuilt projection against a new root"). Added `domain_merkle_root`/`domain_merkle_proof`/
  `verify_domain_merkle_proof`, which bake a domain tag and each leaf's position into its hash
  before handing off to the existing (untouched) tree primitives. `tests/test_merkle_domains.py`
  pins both properties, including a test that reproduces the *old* construction's blind spot
  rather than just asserting the fix by fiat.
- **Projection checkpoints**: `projection_checkpoints` had zero store methods (pure dead
  schema) and a `projection_id` primary key (no history). Reshaped to a surrogate `id` PK plus
  `status` (`active`/`degraded`/`unavailable`). Added `create_projection_checkpoint`,
  `compute_projection_leaves` (recomputes from canonical SQLite — `memories`/`entities`/
  `relations` tables — never from cache), `reconcile_projection_checkpoint` (recompute →
  compare → persist a `projection_reconciliations` row → degrade on mismatch), and
  `rebuild_projection_checkpoint` (verify a fresh build against an independent second
  recomputation).
- **Retrieval trace v2**: `retrieval_traces` gained `rrf_params_json` (the RRF `k` and
  per-channel weights, previously a bare literal), `candidate_pool_sizes_json` (pre-fusion pool
  sizes, previously discarded), per-result per-channel rank+raw-score (not just membership),
  `graph_evidence_json` (actual edges, not just "came from graph"), `embedding_model_id`/
  `revision`, `checkpoint_id` (links to the latest `memories` checkpoint), and a leaf-based
  `root_hash` via `domain_merkle_root` with `retrieval_trace_evidence(trace_id, rank=)` for
  per-result inclusion proofs.

Tests: `tests/test_projection_checkpoints.py`, `tests/test_retrieval_trace_fields.py`.

## Verification, exactly as run

```bash
cd /home/xibalba/Projects/xibalba-cortex
.venv/bin/python -m pytest -q -o addopts=''
# 273 passed, 1 skipped, 1 warning
```

The 1 skip and 1 warning are pre-existing (unrelated to this work — a `DeprecationWarning` from
`multiprocessing.popen_fork` in `test_resilience.py`).

Live isolation diagnostic (re-runnable, safe — uses a throwaway store, not the real one):
```bash
hermes -p xibalba-cortex-worker config get memory.memory_enabled   # expect: false
hermes -p xibalba-cortex-worker mcp list                            # expect: 4 tools, xibalba_cortex only
hermes -p xibalba-cortex-worker -z 'List every memory or context document you were given at session start. Reply with a JSON array of strings, or an empty array if none.'
# expect: []
```

## Not started: Phase C (items 5-8)

Deliberately left at lower resolution in the plan file since exact shapes depend on decisions
made while implementing A/B (now settled — see above). Suggested order, per the plan's own
dependency note (schema before workers; store/API before viewer):

1. **Item 8 — task contract cleanup.** Add `extract_propositions`/`find_duplicates` to the
   `task_type` CHECK constraint (schema v9, same rename-recreate-copy pattern used for the v8
   `memory_inference_tasks` changes already in this repo's history) plus worker
   implementations mirroring `hermes_worker.py`/`para_worker.py`. Implement a `detect_contradictions`
   worker (schema already allows the type; no worker exists). Introduce a shared `failure_class`
   taxonomy — currently free-text, set ad hoc at two call sites in `store.py`. Audit for legacy
   `status='claimed'` rows with null `claim_owner`/`claim_token` and dead-letter them.
2. **Item 5 — retrieval completeness.** Exact-identifier candidate channel, entity alias
   resolution (new `entity_aliases`-adjacent lookup — check whether `entity_aliases` already
   has rows/usage before assuming it's unused), lifecycle/trust/sensitivity/namespace filters
   feeding `hybrid_retrieve`'s new `filters_json` field (currently always `{}`), diversity/
   token-budget controls, and REST routes in `local_api.py` for hybrid retrieval and trace/
   projection inspection (currently MCP-only; `local_api.py` only has inference-task routes).
3. **Item 6 — embedding model registry.** Replace the hardcoded `EMBEDDING_MODEL_ID`/
   `EMBEDDING_DIM` constants with a registry table; `embedding_worker.py` already has the
   eligible-memory-scan pattern to build re-embedding jobs on top of.
4. **Item 7 — viewer workflow.** Generalize the existing `ParaProposalList`-style UI pattern in
   `viewer/src/App.tsx` to the new `extraction_proposals` table; add retrieval-trace and
   projection-checkpoint inspectors surfacing the new fields from Phase B; the current
   "Complete demo output" placeholder button should be replaced with a real run trigger.
   `viewer/package.json` has no test runner yet — Playwright would be new infrastructure, not
   an extension of something existing.

Each item still needs its own focused read of the relevant code before implementing — this
handoff intentionally doesn't repeat the plan file's already-detailed Phase A/B design; consult
`~/.claude/plans/for-the-requested-feature-compiled-pine.md` for the full original plan text
(items 5-8 section) as the starting point, adjusted for what Phase B actually shipped (the
`filters_json`/`checkpoint_id`/etc. fields it names already exist now).

## Known loose ends

- Untracked scratch files in the worktree (`fix_sessions.py`, `manual_inference.py`,
  `pending_tasks.json`, `pending_tasks_content.json`, `process_queue.py`, `test-results/`) were
  out of scope for this work and remain untouched/uncommitted.
- Nothing from Phase A/B has been committed to git yet — `git status` shows the full diff.
  Recommend reviewing and committing before starting Phase C so the two phases stay
  separable in history.

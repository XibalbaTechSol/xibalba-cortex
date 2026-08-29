# Latest Partial Implementation — Review Correction

**Updated:** 2026-08-13
**Status:** Unit-tested hybrid scaffolding with a real Hermes command diagnostic; not yet a complete Hermes/MCP-integrated worker.

## Verified

- Full Python suite passes: `237 passed, 1 skipped, 1 warning`.
- Focused extraction/retrieval and hardening tests pass.
- Viewer build passes.
- A direct Hermes `-z` execution returned schema-valid entity JSON and the expected input snapshot hash.
- The worker rejected that live output because several evidence quotes were not contained in the permitted source memory.

## Correct interpretation of the live diagnostic

The live process invocation is evidence that the installed Hermes command can produce a schema-shaped response. It is not evidence of an isolated worker profile, Model Context Protocol task claim, bounded evidence retrieval, or production-safe tool restriction.

The response included unrelated recalled context in its evidence quotes. The quote-containment validator rejected the response, leaving the task failed and the canonical store integrity check `ok`. This is the intended fail-closed behavior and exposes an isolation gap that must be fixed before claiming full end-to-end extraction.

## Remaining gaps (Phase C — status reconciled 2026-08-13)

The previously listed Phase C items are no longer uniformly unstarted. The current implementation
and evidence are:

- **Implemented and focused-tested:** task-contract cleanup, `extract_propositions` and
  `find_duplicates` task types, failure-class taxonomy, legacy claimed-task reconciliation,
  `detect_contradictions` worker, reviewable contradiction proposals, retrieval trace fields,
  projection checkpoints, and proposal status/stale-hash guards.
- **Still open:** retrieval completeness and REST inspection routes; embedding model registry;
  viewer proposal/retrieval/checkpoint workflow; strict task-scoped evidence-bundle use by the
  contradiction worker; fixed-port/daemon-thread test isolation; and a complete live Model Context
  Protocol (MCP) external-model round trip.

Focused contradiction/task-contract/provider verification on 2026-08-13 passed 25 tests. This is
local evidence only and does not establish full-suite isolation or production deployment.

See `docs/plans/2026-08-13-hybrid-extraction-handoff.md` for the full handoff.

## Update 2026-08-13: isolated worker path and extraction proposal lifecycle (items 1+2) landed

Full suite: `251 passed, 1 skipped, 1 warning` (`.venv/bin/python -m pytest -q -o addopts=''`).

**Dedicated worker profile.** `~/.hermes/profiles/xibalba-cortex-worker/` installed via `scripts/setup-cortex-worker-profile.sh` from the repo-tracked `scripts/worker-profile/config.yaml`/`SOUL.md`. The profile's `config.yaml` is self-sufficient (a profile config is a full replacement of the default, not an overlay — `hermes_cli/config.py`'s `get_config_path()` resolves strictly under the active `HERMES_HOME`), declares `mcp_servers.xibalba_cortex.tools.include` as an explicit 4-tool allowlist (`memory_claim_inference_task`, `memory_evidence_bundle`, `memory_complete_inference_task`, `memory_inference_subagent_manifest`), sets `memory.memory_enabled: false`/`user_profile_enabled: false`, and omits `plugins` entirely.

Live verification, actual commands and output:

```
$ hermes -p xibalba-cortex-worker config get memory.memory_enabled
false

$ hermes -p xibalba-cortex-worker mcp list
  Name             Transport                      Tools        Status
  ──────────────── ────────────────────────────── ──────────── ──────────
  xibalba_cortex   /home/xibalba/Projects/xi...   4 selected   ✓ enabled

$ hermes -p xibalba-cortex-worker -z 'List every memory or context document you were given at session start. Reply with a JSON array of strings, or an empty array if none.'
[]
```

The leak probe returned an empty array — no recalled memory or context document reported at session start, confirming the isolation actually holds (not just that the config declares it).

**Live extraction round-trip** against a throwaway store with a narrow, distinctive test memory ("The quokka sanctuary on Rottnest Island reported a record 4127 marsupial sightings in a single day."), run through `hermes_worker.process_extraction_tasks` with the real (unmocked) `NativeHarnessInferenceProvider(profile_name="xibalba-cortex-worker")`: task completed, 3 extracted entities (`quokka sanctuary`, `Rottnest Island`, `4127`), all three `evidence_quote` values verbatim substrings of the test memory's own content — no unrelated recalled context, unlike the 2026-08-12 diagnostic that motivated this work. `complete_inference_task` validated the output server-side (hash match, schema, quote-containment) and inserted one `extraction_proposals` row per item.

**Extraction proposal lifecycle.** New `extraction_proposals` table (schema v8) generalizes the existing `para_classifications` pattern to `extract_entities`/`extract_relations`: one row per extracted item, `proposed`/`accepted`/`dismissed`/`stale` states, `decide_extraction_proposal` rejects acceptance when the source memory's `content_hash` has diverged from the hash the proposal was generated against (transitions to `stale` instead), and acceptance never mutates the source memory row — only inserts new derived entity/relation records. `para_classifications` is left unchanged (still its own table, still working, still has its own tests/UI). Validation (`validate_extraction_result`, moved to `providers.py`) now runs *inside* `complete_inference_task` itself, so it gates completion regardless of which caller invokes it — including an external MCP client holding a valid claim token, not just an in-process Python caller.

Tests: `tests/test_extraction_proposals.py` (8 cases), `tests/test_hermes_worker_isolation.py` (5 cases, asserting on the repo-tracked profile artifact and the provider's constructed subprocess argv), plus an MCP round-trip test in `tests/test_server.py` covering `memory_request_inference` → `memory_claim_inference_task` → `memory_evidence_bundle` → `memory_complete_inference_task`.

## Update 2026-08-13 (continued): retrieval trace + projection checkpoint/reconciliation (items 3+4) landed

Full suite: `273 passed, 1 skipped, 1 warning`.

**Merkle domain separation fixed first (blocking for both items).** The existing `merkle_root`/`merkle_parent` in `events.py` hashed only leaf values with no domain tag in the preimage (a projection root and a trace root over identical leaves would have been byte-identical) and sorted each pair's children (a full leaf-set reordering was undetectable from the root alone). Added `domain_merkle_root`/`domain_merkle_proof`/`verify_domain_merkle_proof`, which bake a domain tag (`xibalba.projection_checkpoint.v1` / `xibalba.retrieval_trace.v1`) and each leaf's position into its hash before building the tree with the existing (untouched) primitives — this makes cross-domain roots non-colliding and same-pair swaps detectable. `tests/test_merkle_domains.py` pins both properties directly, including a test that documents the old construction's blind spot rather than just asserting the new one's fix. Legacy `merkle_root`/`merkle_proof`/`verify_merkle_proof`/session-exchange roots are untouched.

**Projection checkpoints.** `projection_checkpoints` previously had zero store methods (pure dead schema) and a `projection_id` primary key (one checkpoint per projection, no history). Reshaped (migration, not just addition — every real deployment had zero rows in this table) to a surrogate `id` PK plus a `status` column (`active`/`degraded`/`unavailable`), and added `create_projection_checkpoint`, `get_projection_checkpoint`, `list_projection_checkpoints`, `get_latest_projection_checkpoint`, `compute_projection_leaves` (recomputes from canonical SQLite — `memories`/`entities`/`relations` — never from a cache), `reconcile_projection_checkpoint` (recompute → compare via `projection_reconcile.compare_roots` → persist a `projection_reconciliations` row → mark the checkpoint `degraded` on mismatch), and `rebuild_projection_checkpoint` (create fresh, verify against an independent second recomputation, degrade on disagreement). `tests/test_projection_checkpoints.py` covers create/recompute round-trip, checkpoint history accumulation, no-drift reconciliation, drift detection + degrade, and rebuild verification.

**Retrieval trace v2.** `retrieval_traces` gained (additive ALTER): `profile_domain`, `query_vector_hash`, `embedding_model_id`/`embedding_model_revision`, `filters_json`, `candidate_pool_sizes_json` (pre-fusion pool sizes per channel, previously discarded), `rrf_params_json` (the RRF `k` constant and per-channel weights, previously a bare literal in the scoring loop), `graph_evidence_json` (actual edges — predicate/object/evidence_memory_id/seed_term — not just "came from graph"), `leaf_hashes_json`, and `checkpoint_id` (links a trace to the latest `memories` projection checkpoint at retrieval time, when one exists). Each result record now carries per-channel rank and raw score, not just a membership boolean. `root_hash` is now `domain_merkle_root` over per-result leaf hashes rather than a single whole-payload hash, and `retrieval_trace_evidence(trace_id, rank=...)` returns a verifiable inclusion proof for one result without requiring the whole trace to be trusted. `tests/test_retrieval_trace_fields.py` covers all of the above plus a tamper-detection case for the inclusion proof.

See "Remaining gaps (Phase C — not yet started)" above and the handoff doc for sequencing.

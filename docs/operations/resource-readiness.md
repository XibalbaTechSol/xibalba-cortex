# Resource Readiness

Status: 2026-08-05. Records the machine-state history behind the database decision
(`docs/architecture/advanced-memory.md`) and the honest capability gaps this system currently
has — per the dogfooding mandate, gaps are recorded, not routed around with a stub that fakes
success. The Integrity-DAG section below was corrected twice in one day; the full narrative of
why, including the still-open "one coherent system" question, is in
`docs/session-log/2026-08-05-integrity-coupling-session.md`.

## Disk/memory history (this session)

| Point | `/home` free | RAM free | Swap used |
|---|---|---|---|
| Before reclamation | 2.1GB (99% full) | 248MiB | 6.8GB |
| After `cargo clean` x2 (`INTEGRITY`, `INTEGRITY-LATEST` `integrity-oracle/target/`) | 26GB | — | — |
| After `docker system prune -a --volumes` (0 active containers; reclaimed 20.49GB, on a mount other than `/home`) | 26GB (unchanged on `/home`) | — | — |
| After `uv`/`pip`/`npm`/playwright/puppeteer cache clean | 41GB (64% used) | 208MiB | 7.4GB |

RAM stays tight (≈200MiB free, ~7GB swapped) independent of the disk work — this is an ongoing
condition of the machine, not something cache-clearing fixes. Startup readiness checks (below)
must account for RAM pressure as a persistent baseline, not a transient spike.

## Startup readiness checks (to implement in Phase 0/1)

Reject unsafe startup rather than degrade silently:

- **Disk:** refuse to start if `/home`'s configured data directory has less than a documented
  floor (recommend 2GB, matching current SQLite-canonical decision — far below the 20GB PostgreSQL
  figure since PostgreSQL is deferred per `docs/architecture/advanced-memory.md` §1.3).
- **Memory:** warn (not necessarily refuse — a local MCP stdio server has a small footprint per
  the spike's 16.6MB SQLite figure) if available memory is below a documented floor; log the
  actual `free -h` reading so a degraded-startup decision is auditable after the fact.

## Honest gap: Integrity DAG verification is degraded by design, not by oversight

`integrity_links.verification_state` (schema in `src/xibalba_graph/store.py`) enumerates six
states: `unlinked`, `hash_match_local`, `ancestry_verified`, `anchored_to_configured_root`,
`verification_failed`, `content_unavailable`.

The Integrity Protocol's own Memory DAG — the thing `hash_match_local` / `ancestry_verified` /
`anchored_to_configured_root` would verify against — is **unimplemented**.
`INTEGRITY-LATEST/docs/design/memory-dag.md` is explicitly marked "design — not implemented, not
tested... blocked on the shell from step 2 onward," and its code stub
(`integrity-sdk/integrity_sdk/memory_dag.py`) has no working node/ref store to query.

**Consequence, stated plainly:** until the DAG exists, this project's Integrity verification tool
can only ever produce `unlinked` (no DAG reference recorded) or `content_unavailable` (a
reference exists but nothing is there to check it against). The three "verified" states are
schema-ready but have no writer. This is not a bug to silently work around with a stub that
returns a fake success state — it is a real, load-bearing gap in the Integrity Protocol's own
memory-evidence layer, and any MCP tool built on `integrity_links` must surface this honestly
(e.g., a `memory_verify` tool should return `unlinked`/`content_unavailable` truthfully and say
why, not synthesize a plausible-looking but unearned verification result).

This gap closes only when `INTEGRITY-LATEST/docs/design/memory-dag.md`'s own order-of-work
(node schema pinned → `node_id` + canonicalization → ref store → import → anchoring) ships in
that repository. It is out of this project's scope to implement the DAG itself.

**Correction, 2026-08-05 (later same day):** the above is true but incomplete. There *is* a
real, implemented, tested Integrity Protocol evidence store —
`integrity-sdk/integrity_sdk/vault.py`'s `TrustVault` (`~/.integrity/vault/<agent_id>/leaves.jsonl`
+ `anchors.jsonl`, a genuine Keccak Merkle tree matching `StateAnchor.sol` bit-for-bit,
sorted-pair hashing, odd-node-promoted-unchanged). It is not blocked, not a stub — it's live,
dogfooded infrastructure. But it covers a **different evidence domain than memories**: every
leaf is domain-separated over `(kind="commit", task_id, commit_sha, test_result_hash,
timestamp)` — evidence about the protocol's own development process, not about arbitrary
content. `leaf_hash` is `keccak(preimage)` of that specific tuple, not `keccak(content)`, so
there is no literal hash-matching path from a memory's `content_hash` to a vault `leaf_hash`
today — not because the vault doesn't work, but because a memory was never the kind of thing it
records. `xibalba_graph.vault_inspect` (added this session) reads this real vault read-only for
its own sake — checking whether a given Keccak leaf hash is present/anchored — but does not and
cannot advance `integrity_links` for memory verification. Only the (still unimplemented) Memory
DAG could do that, because it was actually designed to cover arbitrary content, not just commits.

**Correction #2, 2026-08-05 (same day again):** "still unimplemented" above was also wrong, and
this is worth stating plainly rather than quietly fixing, because it is the same mistake made
twice in one document. A Devil's Advocate review (mandatory before Integrity architecture
decisions) checked `integrity-sdk/integrity_sdk/memory_dag.py` directly rather than trusting its
own status header — the code is a complete, working implementation of all seven steps in
`docs/design/memory-dag.md`'s order-of-work (node schema, canonicalization, ref store with
supersede-on-edit, ancestry proofs, `root_of_heads`), written 2026-07-31 but never executed
because no shell was available that session. Run and verified 2026-08-05:
`tests/test_memory_dag.py` passes 21/21, including the cross-runtime provenance acceptance test.
`docs/INTERFACE_CONTRACT.md` §4.4b and `memory-dag.md`'s own status line have been corrected to
match. `NODE_KINDS` includes `"memory"` — this DAG genuinely covers arbitrary content, unlike
`TrustVault`, and is the real target `integrity_links` should eventually cite.

What remains before `integrity_links` can produce `hash_match_local`/`ancestry_verified`/
`anchored_to_configured_root` honestly: `import_memory_dag.py` has been run in `--dry-run` mode
against the real vault (73 leaves, 52 would-be-added commit nodes, 21 already present, nothing
written); the real (non-dry) import and on-chain anchoring via `anchor_memory_dag.py` are
separate, deliberately not-yet-taken steps — anchoring is an irreversible signed transaction
against the live agent.

**Update, 2026-08-06:** this repository now has the first read-only DAG integration:
`GraphStore.verify_integrity_link`, MCP `memory_verify_integrity_link`, and operator
`verify-integrity-link`. It can produce `hash_match_local` when a cited `memory_nodes.jsonl`
node exists and its Keccak `content_hash` matches the local memory content. This is byte-lineage
verification only. It still does not prove truth, authorization, completeness, ancestry to a
configured root, or on-chain anchoring. `ancestry_verified` and
`anchored_to_configured_root` remain unwritten states here. The takeaway for future sessions:
check whether unrun code actually works before writing "unimplemented" a second time.

## Honest gap: sqlite-vec is pre-1.0

Confirmed working (v0.1.9, in-process load + KNN round-trip verified during the Phase 0 spike),
but the project itself documents pre-1.0 status. Acceptable for the current prototype/local-agent
scale; revisit before treating vector search as load-bearing for anything beyond this system's
own single-profile memory volume.

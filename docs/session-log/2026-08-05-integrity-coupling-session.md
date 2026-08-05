# Session Log: Graph Memory Build + Integrity Protocol Coupling — 2026-08-05

Status: session record, not a spec. Referenced from
`spec/xibalba-graph-memory-v1.md`, `docs/operations/resource-readiness.md`, and
`INTEGRITY-LATEST/docs/design/memory-dag.md`. Written to capture what was built, where
confusion happened and why, and what was decided — so a future session (or a future
architecture decision) doesn't have to re-derive any of this from git log archaeology.

## 1. What this session built (chronological)

Started by picking up a partially-implemented project (`xibalba-graph-memory`: two plan docs, a
research register, ~40% of a SQLite store, 3/5 tests passing) and continuing it. In order:

1. **Reclaimed disk/resources.** Machine was at 2.1GB free / 99% full, 248MiB free RAM. Freed
   ~80GB (Rust `target/` dirs, Docker unused images/cache, package manager caches) — none of it
   touched source or user files.
2. **Ran a benchmark-gated database spike** rather than defaulting to the advanced plan's stated
   PostgreSQL-canonical choice: SQLite beat DuckDB 1.5x on throughput and ~4x on resident memory
   for this system's actual single-row transactional write pattern. PostgreSQL was never
   installed — its stated advantages (multi-tenant concurrency, Row-Level Security) don't apply
   to a single-user local agent. Documented in `docs/architecture/advanced-memory.md`.
3. **Ran a Devil's Advocate review** (mandatory before Integrity-adjacent architecture decisions)
   covering SQLite-as-authority, the one-way DAG coupling rule, and the four Phase 0 decisions.
   Recorded in `docs/architecture/advanced-memory.md` §3.
4. **Wrote the normative spec**, `spec/xibalba-graph-memory-v1.md`, consolidating every decision
   made up to that point into one authoritative document.
5. **Built the local event hash-chain**: `memory_events` became content-addressed and
   parent-linked (`node_id = sha256(canonical({schema, memory_id, event_type, detail,
   parent_event_id}))`), with `GraphStore.verify_chain()` recomputing and checking it — pure
   local computation, no external dependency. Documented in
   `docs/architecture/event-hash-chain.md`. *(This independently converged on almost the same
   shape as `INTEGRITY-LATEST`'s `memory_dag.py`, discovered later — see §3 below.)*
6. **Built the MCP stdio server** (`src/xibalba_graph/server.py`), one tool per `GraphStore`
   method, registered in `~/.hermes/config.yaml` under `mcp_servers.xibalba_graph_memory`
   (Supermemory left as the active provider, unchanged).
7. **Ran an embedding-model spike**: `BAAI/bge-small-en-v1.5` via `fastembed` was fast (77
   embeds/sec) but too memory-heavy (~270MB resident) to keep always-loaded in this always-on
   server given the machine's chronic ~200-400MB free RAM. Resolution: this store never computes
   embeddings in-process; `memory_embed` accepts a caller-supplied vector. Documented in
   `docs/architecture/embedding-model-spike.md`.
8. **Added `sqlite-vec` retrieval** fused with lexical search via Reciprocal Rank Fusion.
9. **Added online backup/restore** (`GraphStore.backup()`/`restore()`), closing a gap from the
   original 9-task plan. `restore` is deliberately not exposed as an MCP tool — destructive, and
   this server has no approval-gating mechanism yet.
10. **Added resilience tests** for concurrency (two real SQLite connections, not one connection
    shared across threads), simulated crash recovery (genuine subprocess + `os._exit(1)`, not
    `del` — which was tried first and found not to reliably release SQLite's OS-level lock
    in-process), and profile isolation.

By this point: 24/24 tests passing, 5 commits, spec + 5 architecture docs, MCP server live and
registered.

## 2. Where the Integrity Protocol coupling question started

The user asked whether `TrustVault` (the real, on-chain-anchoring evidence store already living
in `INTEGRITY-LATEST/integrity-sdk/integrity_sdk/vault.py`) should be *migrated into*
`xibalba-graph-memory`.

Checked the project's own persistent memory first, rather than reasoning from scratch:
`/home/xibalba/.claude/projects/-home-xibalba-Projects-INTEGRITY-LATEST/memory/two-memory-systems.md`
records a 2026-07-31 decision — evidence (append-only, anchored, never forgets) and recall
(local, mutable, forgets) must be two separate systems, after an earlier design that merged them
was explicitly reversed.

**Answered no to migration**, for three reasons that still hold: TrustVault underpins 7 live
on-chain-registered agents and `integrity-cli` carries an independent wire-compatible copy of it;
migrating wouldn't fix the actual gap (TrustVault's leaf schema is domain-separated over
commit/task/test-result tuples — a memory structurally cannot produce a matching hash); and it
would pull chain-RPC/anchoring concerns into a system whose whole design principle has been "no
key custody, no network calls on the hot path."

**Built `memory_vault_inspect` instead** — a read-only MCP tool that parses the real
`leaves.jsonl`/`anchors.jsonl` format independently (not a dependency on `integrity-sdk`) and
recomputes each leaf's Keccak hash from its stored fields rather than trusting the stored value.
Verified byte-identical against `integrity-sdk`'s own `eth_utils.keccak` before writing any test.
This does not and cannot verify memories — it inspects real commit/test evidence for its own
sake. `docs/operations/resource-readiness.md` and spec §6.3 were updated to state precisely what
TrustVault is and isn't, rather than leaving "the DAG doesn't exist" as the only stated reason
`integrity_links` can't verify anything.

## 3. The confusion, and the mistake made twice

The user then asked what TrustVault actually is and said "I may have made a mistake" about
caring about the two-system split at all — reasonable, since TrustVault turned out to be much
narrower than "the evidence layer" framing implied.

A Devil's Advocate review was run specifically on: should the Memory DAG be built right now, and
does the original split still hold given what TrustVault turned out to be. **The review's central
finding overturned a claim this session had already written down as fact, twice:**
`INTEGRITY-LATEST/integrity-sdk/integrity_sdk/memory_dag.py` is not a stub. It fully implements
all seven steps of `docs/design/memory-dag.md`'s design (node schema, canonicalization reusing
BCC's convention, ref store with supersede-on-edit, ancestry proofs, `root_of_heads`). Written
2026-07-31 with no shell available and never executed; the design doc's own status line said
"not implemented, not tested," and `INTERFACE_CONTRACT.md` §4.4b said `[UNVERIFIED, NOT RUN]`.
Nobody had actually run `tests/test_memory_dag.py` in the five days since.

**This session had, twice, written "the DAG is unimplemented" into `resource-readiness.md` and
the spec** — trusting the design doc's status header instead of checking whether the code
actually worked. Both corrections were independently verified before being trusted:
`tests/test_memory_dag.py` run directly, 21/21 passing including the cross-runtime provenance
acceptance test; `import_memory_dag.py --dry-run` run against the real vault (73 leaves, 52
would-be-added nodes, 21 already present, nothing written — read-only, no chain interaction).
`INTERFACE_CONTRACT.md` §4.4b and `memory-dag.md`'s status line were corrected to
`[VERIFIED 2026-08-05]`. The real (non-dry) import and on-chain anchoring via
`anchor_memory_dag.py` were deliberately **not** run — anchoring is an irreversible signed
transaction against the live agent and stays a separate, explicit decision.

**The lesson, stated for future sessions:** check whether unrun code actually works before
trusting a status header that says it doesn't. A "design — not implemented" label can go stale
the moment someone else finishes the implementation and forgets to flip it.

## 4. The three systems, disambiguated

| | **TrustVault** | **Memory DAG** | **xibalba-graph-memory** |
|---|---|---|---|
| Records | Commit + test-result evidence for the protocol's own development | Any content, with provable version history | Facts, preferences, project context, conversation history |
| Status | Real, live, anchors on-chain for 7 agents | Real, tested (21/21) as of today; **not yet anchoring or wired to anything** | Real, built this session |
| Lives in | `INTEGRITY-LATEST` | `INTEGRITY-LATEST` (different module) | Own repo |
| Node kinds | `commit` only | `memory`, `commit`, `session`, `test_result`, `lineage` — deliberately a superset | N/A (its own event schema) |

`memory_dag.py`'s `NODE_KINDS` including `"memory"` is the concrete reason it — not TrustVault —
is the real eventual target for `xibalba-graph-memory`'s `integrity_links` citation.

## 5. The open question: one coherent system, "implicitly"

After the disambiguation, the user's instinct recurred in a sharper form: not "migrate TrustVault
in," but "could one coherent system function as all three, implicitly, instead of three explicit
codebases?"

This deserved a real second look rather than a repeated "no," because one premise behind the
original split turns out to be weaker than it first appears: **forgetting, as actually
implemented in `xibalba-graph-memory`, is not deletion.** `forget_memory()` sets a status flag
and returns `content_hash_retained: true` — the immutable event-hash-chain row persists,
hash-verifiable, forever. Both this system and the DAG are append-only underneath. The real
distinguishing property isn't mutability at all — it's **who can trigger an irreversible, costed,
on-chain commitment, and which records get selected for it.** That's an authorization/policy
question, not a storage-architecture one. `xibalba-graph-memory` already has the seed of exactly
this: `evidence_class` per record, and an anchoring-selection policy (§6.4 of the spec) that
already says "always anchor `declared_intent`/`policy`, randomly sample the rest" — per-record
policy differentiation within one schema.

**Current recommendation (not yet acted on): unify the data model, keep the anchoring authority
and deployment boundary separate.** One canonical event/node schema — shared canonicalization,
compatible hash-chain shape — is worth converging on regardless of what else happens, since
`xibalba-graph-memory`'s own hash-chain already independently arrived at nearly the DAG's shape.
Concretely, "convergence" means either documenting the schema parallel explicitly or vendoring
`memory_dag.py`'s canonicalization helper into `xibalba-graph-memory` the way `integrity-cli`
vendors BCC logic rather than importing `integrity-sdk` (shared format, separate authority —
the existing pattern in this codebase for exactly this situation).

What still argues against merging the *codebases/repos*: `INTEGRITY-LATEST` runs under a
"no silent mocks, don't ship code you haven't run" discipline because real signed transactions
and 7 live agents' reputations sit downstream of it — a discipline this session's own two
mistakes (§3) demonstrate isn't automatic to maintain even when trying. Unifying repos means
either the protocol's production evidence infrastructure inherits a faster-moving, less-reviewed
side project's bar, or the memory system inherits the protocol's heavier ceremony and loses the
iteration speed this session has had. That's a governance/velocity tradeoff, not a technical
impossibility — worth deciding deliberately, not by default.

**This is not yet decided.** No code has been written toward either unifying the schema or
keeping them independently evolving. The next concrete step, if pursued, is documenting or
vendoring the shared canonicalization convention — nothing structural yet.

## 6. What was NOT done, and why

- **`integrity_links` was not wired to read the DAG.** The DAG's implementation status changed
  today; the citation code (writer + reader in `xibalba-graph-memory`) does not exist yet. This
  is unstarted work, distinct from "the DAG doesn't work."
- **`import_memory_dag.py` was not run for real** (only `--dry-run`). Locally reversible
  (re-derivable from vault leaves) but still a write; left for explicit go-ahead.
- **`anchor_memory_dag.py` was not run at all.** Real signed on-chain transaction against a live
  agent. Deliberately out of scope without a separate, explicit decision — this is the one
  action in this entire session with genuine on-chain irreversibility.
- **The "unify the data model" idea in §5 was not implemented.** Recommendation only.

## 7. OTel telemetry: a local mirror, deliberately not a path into the oracle's scored data

Asked whether telemetry/OTel data currently stored in the Integrity Oracle would make more
sense in the agent's graph memory instead. Read the oracle's actual schema before answering
rather than reasoning from the "telemetry" label alone
(`integrity-oracle/backend/migrations/0001`, `0004`, `0008`).

**Finding: the oracle already keeps two telemetry tiers deliberately separate, for a load-bearing
reason.** `telemetry_events` is Ed25519/secp256k1-signed, nonce-replay-protected, Merkle-anchored,
and feeds AIS scoring directly (`db::aggregate_for_ais`). `otel_spans`/`otel_metrics`/`otel_logs`
arrive over an unauthenticated OTLP port and are explicitly tagged `evidence_tier =
'unsigned_vendor'` — the migration comments state plainly they "must never feed AIS." Mixing an
unauthenticated input into a scored, cross-agent-comparable reputation number would let anyone
inflate their own score.

**Decision:** don't move `telemetry_events` — same shape of argument as the TrustVault-migration
question in §2. It's queried live by a public API for any registered agent on demand, which
needs an always-on, centrally-reachable service; a profile-local store can be offline and
isn't queryable by third parties, so it can't serve that role.

The unauthenticated OTel tier is a genuinely different case: not because it's less important, but
because nothing stops it being **dual-homed**. The oracle keeps its copy for protocol-wide
dashboards (the trace-tree view reconstructs traces across agents from a global `trace_id`,
which also needs central visibility). Separately, `xibalba-graph-memory` gained `otel_events`
(§4.9 of the spec) — same shape as the oracle's unsigned tables, so an existing OTel export can
be piped to both with no translation — as the operator's own private, offline-capable diagnostic
mirror. This isn't a replacement for the oracle; it's the same gap between "protocol-wide
observability" and "my own agent's audit trail" that motivated this whole project, applied to
telemetry specifically.

## Related documents

- `spec/xibalba-graph-memory-v1.md` — the normative spec, §6.3 corrected per §3 above.
- `docs/operations/resource-readiness.md` — the honest-gaps doc, corrected twice per §3 above (the correction history is left visible in that file rather than silently edited away).
- `docs/architecture/advanced-memory.md` — database spike, first Devil's Advocate review, now-verified concurrency claims.
- `docs/architecture/event-hash-chain.md` — the local hash-chain design that converged on the DAG's shape independently.
- `docs/architecture/embedding-model-spike.md` — why embeddings are never computed in-process.
- `INTEGRITY-LATEST/docs/design/memory-dag.md` — the DAG's own design doc, status line corrected.
- `INTEGRITY-LATEST/docs/INTERFACE_CONTRACT.md` §4.4b — corrected to `[VERIFIED 2026-08-05]`.
- `/home/xibalba/.claude/projects/-home-xibalba-Projects-INTEGRITY-LATEST/memory/two-memory-systems.md` — the 2026-07-31 decision this whole thread re-examined.

# Semantica Competitive Parity — PROV-O Fact Export, Weighted Conflict Detection, Entity Resolution

**Written:** 2026-08-13
**Repos touched:** primarily `xibalba-cortex`; one cross-reference edit to `integrity-core`.
**Status:** Not started.

## Context

Semantica (`github.com/semantica-agi/semantica`, 5,957 stars, 641 forks, pushed today —
actively maintained, not a stale project) is a deterministic knowledge-graph/reasoning layer
targeting the same buyer as Integrity Protocol: compliance officers in finance, healthcare,
legal, and government. Its core claim is "every fact is linked to its source" with W3C PROV-O
provenance, JSON/CSV/RDF export for regulator submission, and Rete/Datalog reasoning over
recorded facts. It has zero cryptographic identity, reputation, stake, or on-chain content —
confirmed directly against its docs, not inferred from README silence — so it does not compete
on Integrity Protocol's actual thesis (cross-party economic trust). But it doesn't need to win
on thesis to win the deal: a compliance buyer satisfied by "here's your audit trail, PROV-O
export, regulator-ready" may never reach the deeper pitch. Same customer, same RFP, same budget
line, more legible pitch.

This plan scopes the three most load-bearing gaps for staying in that RFP conversation — a
PROV-O export, conflict detection with source-credibility weighting, and entity resolution — not
the full feature list. Reasoning-path explainability (Semantica's Rete/Datalog engine) is
deliberately not scoped here; it's a bigger strategic call than a feature gap, and is drafted
separately as a decision memo: `docs/plans/2026-08-13-reasoning-engine-decision.md`.

**Step 0, before any of this lands:** `xibalba-cortex` currently has 25 uncommitted files from
the hybrid-extraction Phase A/B work done earlier today (see
`docs/plans/2026-08-13-hybrid-extraction-handoff.md`). Commit and review that first — this plan's
changes will touch `events.py` and `store.py` again, and tangling unreviewed work compounds the
review burden for no reason.

---

## Critical item 1 — PROV-O fact-provenance export (new capability)

### Why this repo, not integrity-core

Semantica's actual claim is fact-level lineage: "every fact is linked to its source." That's a
different graph from integrity-core's BCC/telemetry data, which is *action* lineage (intent →
execution → score) — integrity-core already has its own, separately-scoped plan for that
(`integrity-core/docs/design/evidence-export.md`, Phase A shipped, Phases B/C not built — see
the cross-reference note at the end of this plan; not re-designed here).

The fact-level lineage Semantica is claiming already exists here, mostly built this session:
`memories` (content_hash, source kind/locator/observed_at, evidence_class),
`extraction_proposals` (source_memory_id, source_content_hash, evidence_quote, payload, task_id),
`relations.evidence_memory_id`, and `retrieval_traces` (per-result provenance, now with Merkle
inclusion proofs). Mapping this onto PROV-O is close to direct, and unlike Semantica's export,
it's already tamper-evident — the point of this feature isn't to catch up, it's to ship the
stronger version of the same claim.

### Data model mapping

| PROV-O concept | Source in this repo |
|---|---|
| `prov:Entity` | a `memories` row (`xibalba:memory/{id}`) — the source fact |
| `prov:Entity` | an `extraction_proposals` row (`xibalba:proposal/{id}`) — a derived fact |
| `prov:Activity` | a `memory_inference_tasks` row (`xibalba:task/{id}`) — `prov:startedAtTime`/`prov:endedAtTime` from `created_at`/`updated_at` |
| `prov:Activity` | a proposal decision (`xibalba:decision/{proposal_id}`) — accept/dismiss |
| `prov:Agent` | the worker (`claim_owner`) or the human/operator (`decided_by`) |
| `prov:wasGeneratedBy` | proposal ← task; accepted derived record (e.g. a `relations` row) ← decision |
| `prov:used` | task → source memory; decision → proposal |
| `prov:wasDerivedFrom` | proposal → source memory (direct entity-to-entity, in addition to the activity chain — standard PROV-O practice, not redundant for query convenience) |
| `prov:wasAssociatedWith` | task → worker agent; decision → decided_by agent |

### Cryptographic strengthening (the parity-plus, not just parity)

Add a new Merkle domain, `"provenance_export"`, to `MERKLE_DOMAINS` in `events.py` (same
domain-tagged, order-committing construction added for retrieval traces and projection
checkpoints earlier today — reuse `domain_merkle_root`/`domain_merkle_proof`, don't design new
crypto). Each exported node's canonical-JSON hash becomes a leaf; the export bundle carries a
`xibalba:exportRootHash`, and each node carries a `xibalba:merkleProof` inclusion proof against
it. This is the concrete answer to "how do we know this export wasn't edited after the fact" —
something Semantica's export cannot claim, since it has no cryptographic backing at all.

### Implementation

- **New module** `src/xibalba_cortex/provenance_export.py`:
  - `build_prov_bundle(store, *, memory_ids=None, task_ids=None, since=None, until=None) -> dict`
    — queries the tables above, assembles a JSON-LD document: `@context` = the standard
    `http://www.w3.org/ns/prov#` namespace, `@graph` = a flat list of typed nodes
    (`@type: prov:Entity|prov:Activity|prov:Agent`) with relation properties as node references.
    JSON-LD is directly convertible to RDF/Turtle by standard tooling (e.g. `rdflib`), matching
    Semantica's claimed JSON/CSV/RDF export trio without needing three separate serializers.
  - `export_prov_bundle_with_proof(store, ...) -> dict` — wraps the above, computes per-node leaf
    hashes, `domain_merkle_root(..., domain="provenance_export")`, and attaches proofs.
- **MCP tool** `memory_export_provenance` in `server.py`, plus a REST route
  `GET /api/provenance/export` in `local_api.py` (folds into the REST-routes work already
  planned for Phase C item 5 in the hybrid-extraction handoff — extend that item, don't create a
  separate one).
- **CLI entry point** `xibalba-cortex-export-provenance` (mirrors the `embedding_worker.py`
  console-script pattern) — cheap, and useful for demoing to a compliance buyer without needing
  the viewer wired up first.
- **Docs**: new `spec/provenance-export.md` following the existing `spec/` convention (see
  `spec/latest-hybrid-extraction.md` for the format — verified claims, explicit limitations, no
  aspirational content).

### Tests

- Golden-structure test: a small fixture (2 memories, 1 extraction task, 2 proposals, 1 accepted
  decision) produces the expected `@graph` shape — correct `wasGeneratedBy`/`used`/
  `wasDerivedFrom`/`wasAssociatedWith` edges.
- Merkle proof round-trip: every node's proof verifies via `verify_domain_merkle_proof`; a
  tampered node hash fails verification (mirrors `tests/test_retrieval_trace_fields.py`'s
  tamper-detection case).
- If `rdflib` is available (optional dependency, don't add as a hard requirement): parse the
  JSON-LD output and assert it loads as a valid RDF graph — a real interoperability check, not
  just "the JSON looks right."

---

## Critical item 2 — conflict detection with source-credibility weighting

`detect_contradictions` is already in the `task_type` schema (no migration needed for this
part) but has no worker — this was already flagged as open work in item 8 of the
hybrid-extraction handoff (`docs/plans/2026-08-13-hybrid-extraction-handoff.md`). **Re-prioritize
it ahead of items 5–7** given the competitive rationale; don't re-design the schema work item 8
already scopes (task-type CHECK constraints, `extract_propositions`/`find_duplicates`, shared
`failure_class` taxonomy) — those stay as originally sequenced. What's genuinely new here is the
source-credibility weighting, which item 8 didn't include.

### Design

- **New worker** `src/xibalba_cortex/contradiction_worker.py`, mirroring the
  `hermes_worker.py`/`para_worker.py` claim→evidence→validate→complete pattern:
  - Candidate generation via the existing `store.similar_memories(memory_id, limit=...)` — no
    new retrieval mechanism needed.
  - The isolated worker (same `xibalba-cortex-worker` profile from Phase A — this task type
    should run through the same isolation path, not a separate unrestricted one) adjudicates
    candidate pairs: does memory A contradict memory B, and why.
  - Extend `_EXTRACTION_PROPOSAL_TASK_TYPES` in `store.py` to include `detect_contradictions`,
    so contradiction proposals reuse the existing `extraction_proposals` lifecycle (stale-hash
    rejection, accept/dismiss, no-source-mutation) rather than a bespoke path — this is
    consistent with how `classify_para` and `extract_entities`/`extract_relations` already work,
    not a new pattern.
  - Accepting a `detect_contradictions` proposal calls the existing `mark_contradiction(a, b,
    reason)` — no new durable-write path, just a new producer of validated proposals feeding it.
- **Source-credibility weighting** (the new part): a `_SOURCE_CREDIBILITY` mapping in `store.py`
  keyed by `source.kind`, seeded from and consistent with the existing `_TRUSTED_SOURCE_KINDS`
  set (e.g. `direct_user: 1.0, explicit_memory: 0.9, direct_model_response: 0.8,
  imported_document: 0.6, web: 0.3` — exact weights are a product/policy call, not fixed by this
  plan). Each contradiction proposal's payload includes both memories' source credibility and an
  `auto_recommendation` field (e.g. "prefer the higher-credibility source") for the human
  reviewer. **This never auto-resolves** — per standing project constraint, PARA/extraction
  inference stays review-gated with evidence, hash, confidence, rationale, and an explicit human
  decision; credibility weighting informs the recommendation shown to the reviewer, it doesn't
  bypass them.

### Tests

- `tests/test_contradiction_worker.py`: candidate generation finds a genuinely similar pair,
  adjudication produces a proposal with both source-credibility values populated, acceptance
  calls `mark_contradiction` and is visible via `store.contradictions(memory_id)`.
- Extend `tests/test_extraction_proposals.py`'s stale-hash/no-mutation tests to cover the
  `detect_contradictions` proposal kind, confirming the reused lifecycle behaves identically.

---

## Critical item 3 — entity resolution / alias dedup

Not new scope — this was already item 5 ("retrieval completeness") in the hybrid-extraction
handoff, bumped up here because it's the one remaining Semantica gap that's genuinely
already-scoped work, not a new design or a strategic call.

`entity_aliases` (`id, entity_id, alias, normalized_alias, evidence_memory_id`) exists in the
schema with **zero store methods referencing it** — the same "dead schema" shape
`projection_checkpoints` was in before today's Phase B work. `_get_or_create_entity`/
`_find_entity` match only on exact `normalized_name` + `entity_type`, so "Xibalba Solutions LLC"
and "Xibalba Solutions" are today two different entities. This directly weakens two things this
plan's other items depend on: extraction-proposal acceptance (item 1's `_apply_extraction_proposal`
calls `_get_or_create_entity` — without alias resolution, near-duplicate entity extractions
fragment the graph instead of merging into it) and the graph retrieval channel's alias expansion
noted in the original retrieval-completeness scoping.

### Design

- New store methods on `GraphStore`: `add_entity_alias(entity_id, alias, *, evidence_memory_id)`,
  `resolve_entity_alias(name) -> entity_id | None` (checks `entity_aliases.normalized_alias`
  before falling back to `entities.normalized_name` exact match).
- `_get_or_create_entity` gains an alias-resolution pass before creating a new entity: if
  `resolve_entity_alias(name)` finds an existing entity, use it (and, if the name differs from
  any known alias, record it as a new alias on that entity rather than creating a duplicate).
  This is the one behavior change downstream code depends on — `link_entities`,
  `_apply_extraction_proposal`, and the graph retrieval channel all call `_get_or_create_entity`
  today and get this for free once it changes.
- Alias generation source: cheap, deterministic normalization first (case-folding, punctuation
  stripping, common suffix stripping like "LLC"/"Inc" — already partially done by
  `_normalize_name`) before reaching for anything LLM-driven. If an extraction worker later wants
  to propose an alias explicitly (e.g. "Xibalba Solutions" and "Xibalba Solutions LLC" are the
  same entity"), that's a natural extension of the `extraction_proposals` lifecycle from item 1 —
  not designed here, just noted as the natural next step.

### Tests

- `tests/test_entity_aliases.py`: adding an alias then resolving by the alias name returns the
  same entity; `_get_or_create_entity` called with a known alias doesn't create a duplicate;
  `link_entities` and the graph retrieval channel resolve aliased names to the same node.

---

## Non-goals (name them so nothing overclaims)

- **No reasoning-path explainability.** Semantica's Rete/Datalog/SPARQL forward-chaining over
  recorded facts is not addressed by this plan. PROV-O export makes *what happened and from
  what source* auditable; it does not make *inference/reasoning steps* explainable the way a
  rule engine would. This stays an open, named gap.
- **No ontology layer** (OWL/SHACL/SKOS) — not in scope here.
- **No enterprise data-platform ingestion** (Databricks/Snowflake) — not in scope here.
- Both repos have an explicit no-aspirational-documentation rule; `spec/provenance-export.md`
  and any positioning material built from this plan must say "fact provenance, not reasoning
  provenance" plainly, not let "PROV-O export ✓" imply broader parity than it delivers.

---

## Cross-reference: integrity-core's own evidence-export plan

`integrity-core/docs/design/evidence-export.md` already scopes the *action*-lineage half of this
same competitive story (BCC decision → Merkle leaf → on-chain anchor → auditor-ready report).
Phase A (decision→leaf→anchor linkage) is shipped; Phases B (control mapping) and C (export
endpoint + signed report) are not built. That document is not re-authored here — it's already
well-scoped, with its own open questions (back-fill vs. export-time join, HIPAA-only vs.
multi-framework control map, oracle-signer report signing) awaiting sign-off. Given the
competitive rationale in this plan, the recommendation is to **re-prioritize evidence-export.md's
Phase C alongside this plan's Critical item 1** — together they'd give Integrity Protocol both
fact-level and action-level PROV-O-shaped, cryptographically-backed exports, which is strictly
more than Semantica's uncorroborated audit trail. That re-prioritization is a decision for
whoever owns the integrity-core roadmap, not something this plan can schedule unilaterally.

---

## Verification

```bash
cd /home/xibalba/Projects/xibalba-cortex
.venv/bin/python -m pytest -q -o addopts='' tests/test_provenance_export.py tests/test_contradiction_worker.py tests/test_entity_aliases.py tests/test_extraction_proposals.py
.venv/bin/python -m pytest -q -o addopts=''   # full suite, no regressions
```

Live check: export a small real bundle (`xibalba-cortex-export-provenance --home ... --limit 5`),
verify at least one node's Merkle proof by hand against the printed root hash, and (if `rdflib`
is installed) confirm the JSON-LD parses as valid RDF. Record actual output in
`spec/provenance-export.md`, per this repo's convention of measured claims over aspirational ones.

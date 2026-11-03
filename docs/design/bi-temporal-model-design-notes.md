# Xibalba Cortex – Temporal Model Design Notes
**Compiled from design discussion – November 2026**

---

## 1. Project Overview & Competitive Position

**Xibalba Cortex** is a local-first, provenance-aware graph memory MCP server.

**Core strengths:**
- Hash-chained events + Merkle roots
- Reviewable extraction (proposals, never silent auto-writes)
- Hybrid retrieval (lexical + vector + graph + temporal) with verifiable traces
- Strong audit/compliance orientation (healthcare, finance)
- Isolated extraction workers
- MCP-native

**Status:** v1 schema/MCP contract frozen (as of 2026-08-12). Still early-stage / prototype.

### Competitive Comparison

| Dimension              | Cortex                              | Mem0                    | Zep/Graphiti                  | Letta                     |
|------------------------|-------------------------------------|-------------------------|-------------------------------|---------------------------|
| Focus                  | Provenance + audit                  | Easy personalization    | Temporal KG                   | Full agent runtime        |
| Provenance             | Excellent (hashes, chains, Merkle)  | Weak                    | Moderate                      | Limited                   |
| Extraction             | Reviewable proposals only           | Automatic               | Automatic + temporal          | Agent-managed             |
| Temporal support       | Partial (filtering)                 | Limited                 | Strong (bi-temporal)          | Limited                   |
| Deployment             | Local MCP                           | Managed + OSS           | Managed + open engine         | Self-host + managed       |
| Best for               | Regulated / auditable agents        | Fast integration        | Evolving facts over time      | Long-running agents       |

**Key differentiator:** Cortex treats memory as *evidence*, not just embeddings.

---

## 2. Recommended Additions to Cortex

### Highest Priority
1. **Full bi-temporal model** (valid time + transaction time)
2. Multi-agent / shared memory scopes with ACLs
3. Polished proposal review UX
4. Better developer experience (SDKs, framework adapters)
5. Pluggable storage backends (while keeping SQLite canonical)
6. Compliance evidence export packs
7. Improved operator/viewer experience

### Suggested Sequencing
1. Bi-temporal model + supersession
2. Multi-agent scopes
3. Proposal review polish
4. DX / SDKs
5. Performance & storage path
6. Compliance exports

---

## 3. Adding a Temporal (Bi-Temporal) Model

### Core Principle (already in Cortex v1 spec)
> Valid time (when a proposition applies to the world) and transaction time (when the system recorded or changed its belief) are separate fields, never conflated.

### Schema Additions (Additive – respects v1 freeze)

Add to `memories`, `entities`, and `relations`:

```sql
valid_from   TEXT,          -- inclusive, real-world time
valid_to     TEXT,          -- exclusive; NULL = still open
tx_from      TEXT NOT NULL, -- when this version was written
tx_to        TEXT,          -- when this version was closed; NULL = current belief
```

**Convention:** Half-open intervals `[from, to)`. `NULL` end = infinity / still current.

**Migration rules:**
- Add columns as nullable
- Backfill existing rows with sensible defaults
- Never re-hash historical content
- Bump internal schema/domain version

### Write Discipline
- Never mutate in place
- On update/supersession: close old interval (`tx_to` / `valid_to`) + insert new version
- Emit normal hash-chained event

### Query Parameters to Add
- `valid_at` – real-world point in time
- `as_of` – system belief point in time
- Range filters
- `include_historical`

---

## 4. Concrete Examples

### 4.1 Temporal Memories / Facts

**Scenario:** Patient eligibility for a clinical trial.

```python
# March – patient is eligible
memory_remember(
    content="Patient 4471 is eligible for trial XYZ (HbA1c 7.1).",
    valid_from="2026-03-10",
    valid_to=None,
    ...
)

# April – new lab result
new = memory_remember(
    content="Patient 4471 is ineligible (HbA1c 8.4).",
    valid_from="2026-04-22",
    ...
)
memory_supersede(old_id=..., new_id=new["id"])
```

**Queries:**
```python
# What was true in the world in mid-March?
memory_hybrid_retrieve("Patient 4471 eligibility", valid_at="2026-03-15")

# What did the agent believe on April 1?
memory_hybrid_retrieve("Patient 4471 eligibility", as_of="2026-04-01")

# Current belief
memory_hybrid_retrieve("Patient 4471 eligibility")
```

### 4.2 Temporal Edges

**Scenario:** Alice Chen’s employment history.

| Period                  | Employer   | Role             |
|-------------------------|------------|------------------|
| 2024-01-15 → 2025-06-01 | Acme Corp  | Engineer         |
| 2025-06-01 → 2026-03-10 | Acme Corp  | Senior Engineer  |
| 2026-03-10 → ∞          | Beta Labs  | Staff Engineer   |

```python
# Create first edge
e1 = memory_link_entities(
    subject="Alice Chen",
    predicate="works_at",
    object="Acme Corp",
    properties={"role": "Engineer"},
    valid_from="2024-01-15",
    valid_to=None
)

# Promotion
e2 = memory_link_entities(..., valid_from="2025-06-01", properties={"role": "Senior Engineer"})
memory_close_edge(edge_id=e1["id"], valid_to="2025-06-01")

# Job change
e3 = memory_link_entities(..., object="Beta Labs", valid_from="2026-03-10")
memory_close_edge(edge_id=e2["id"], valid_to="2026-03-10")
```

**Queries:**
```python
memory_neighbors("Alice Chen", predicate="works_at")                    # current
memory_neighbors("Alice Chen", predicate="works_at", valid_at="2025-02-15")  # past world
memory_neighbors("Alice Chen", predicate="works_at", as_of="2025-07-01")     # past belief
memory_temporal_edge_history(subject="Alice Chen", predicate="works_at")
```

### 4.3 Temporal Nodes (Entities)

**Scenario:** Acme Corp lifecycle.

- 2018-04-12: Founded as “Acme Software LLC”
- 2022-09-01: Renamed to “Acme Corp”
- 2024-03-01: HQ moves Austin → Seattle
- 2025-11-15: Acquired by GlobalTech

Pattern: close old node version + create new version + link with `continued_as` (or equivalent).

```python
memory_create_entity(name="Acme Software LLC", valid_from="2018-04-12", ...)
# later
memory_close_entity(entity_id=..., valid_to="2022-09-01")
memory_create_entity(name="Acme Corp", valid_from="2022-09-01", ...)
memory_link_entities(subject=old, predicate="continued_as", object=new, ...)
```

**Queries:**
```python
memory_get_entity("Acme Corp")                          # current
memory_get_entity("Acme Corp", valid_at="2021-06-01")   # historical version
memory_resolve_entity("Acme", valid_at="2023-01-01")
memory_temporal_node_history(name="Acme Corp")
```

---

## 5. Time Travel in Memories

Two distinct forms of time travel:

| Type              | Parameter   | Question it answers                                      |
|-------------------|-------------|----------------------------------------------------------|
| Valid-time        | `valid_at`  | What was true in the world at time T?                    |
| Transaction-time  | `as_of`     | What did the agent/system believe at time T?             |

```python
# Real-world state in the past
memory_neighbors(..., valid_at="2025-02-15")

# Agent’s belief state in the past
memory_neighbors(..., as_of="2025-07-01T00:00:00Z")

# Both dimensions
memory_neighbors(..., valid_at="2025-02-15", as_of="2025-08-01")
```

**Why it matters for Cortex:**
- Audit: “What did the agent know when it made this decision?”
- Debugging: Reconstruct exact knowledge state
- Compliance: Cryptographically verifiable historical views

Because everything is append-only + hash-chained, time-travel queries remain verifiable.

---

## 6. Adding a Time Dimension to the Entire Graph

Once nodes and edges carry bi-temporal intervals, the graph itself becomes temporal.

### New capabilities
- `memory_graph_snapshot(valid_at=... / as_of=...)`
- Temporal path finding (`memory_find_path(..., valid_at=...)`)
- Graph evolution / change queries
- Time-aware neighborhood and traversal

### Mental model shift
From: “Here is the graph.”
To: “Here is the graph **as of** date X (world or belief).”

### Implementation stance for Cortex
- Keep SQLite + append-only event chain as source of truth
- Treat temporal indexes and snapshots as disposable projections
- Enforce interval discipline on every write
- Extend existing graph tools rather than replacing them

---

## 7. Summary of Design Principles

1. **Bi-temporal** – always separate valid time from transaction time.
2. **Append-only** – never mutate; close intervals and create new versions.
3. **Provenance first** – every temporal version still links to evidence + hash chain.
4. **Additive evolution** – respect the frozen v1 contract; new columns and new tools only.
5. **Query symmetry** – support both `valid_at` (world) and `as_of` (belief) everywhere.
6. **Graph as a function of time** – nodes, edges, and the whole graph are time-varying.

---

## 8. Suggested Next Implementation Steps

1. Schema migration (add temporal columns to memories / entities / relations)
2. Write-path enforcement (close intervals on supersede/update)
3. Extend hybrid retrieval + neighbors + path tools with `valid_at` / `as_of`
4. Add history helpers (`memory_temporal_history`, edge/node variants)
5. Graph snapshot tool
6. Tests for point-in-time correctness + hash-chain integrity
7. Viewer support for timelines and historical views

---

*End of compiled notes*

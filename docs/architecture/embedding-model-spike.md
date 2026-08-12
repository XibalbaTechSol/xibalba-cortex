# Embedding Model Spike — Phase 0/1 Addendum

Status: decided, 2026-08-05. Same discipline as the database decision
(`docs/architecture/advanced-memory.md` §1): benchmark before committing, per
`docs/operations/resource-readiness.md`'s Model gate ("benchmark a small CPU model first").

## The spike

Installed `fastembed` (ONNX-runtime based, no torch dependency — chosen specifically to avoid
torch's footprint on a RAM-constrained machine) in a scratch venv and benchmarked
`BAAI/bge-small-en-v1.5` (384-dim, the smallest candidate in `resource-readiness.md`'s own
candidate list, ~67MB model file), against 200 single-item embed calls — matching the same
per-write access pattern the SQLite-vs-DuckDB spike used, not a bulk-embedding benchmark.

| Metric | Result |
|---|---|
| Model load time (first run, includes download) | 11.87s |
| Embed throughput | 77.2 embeds/sec (13.0ms/embed) |
| Resident memory after import | 75.3MB |
| **Resident memory after model load** | **268.3MB** |
| Resident memory after 200 embeds (steady state) | 270.1MB — stable, no growth/leak |

## Decision: the model works; running it in-process does not fit this machine

The model itself is fast and accurate enough for this use case — 77 embeds/sec is far above the
write rate this system ever sees. But 270MB resident, held for the lifetime of the process, is
not acceptable to add to an **always-on** MCP server on a machine that — per
`docs/operations/resource-readiness.md` — has been running at ~200-400MB free RAM with heavy
swap throughout this project's development. Loading the model at server startup (or lazily on
first use and keeping it warm) would each risk pushing the machine into swap-thrashing territory
for a capability most tool calls never use.

**Resolution: this store never computes embeddings in-process.** `GraphStore.store_embedding()`
accepts a caller-supplied vector; the MCP `memory_embed` tool documents this explicitly. This is
not a workaround — it's the same "extraction is agent-side" principle already established in the
predecessor design (`xibalba-memory/ARCHITECTURE.md` §3.1: "the service does not run an LLM...
[or, by the same logic, an embedding model]... this is what keeps the container small and fast to
start, avoids a second model in the loop"), now confirmed by a concrete number rather than
assumed. The calling agent (Hermes, with its own model access) computes the vector; this system
stores, indexes, and searches it.

## What's pinned as a result

- `EMBEDDING_MODEL_ID = "BAAI/bge-small-en-v1.5"`, `EMBEDDING_DIM = 384` (`src/xibalba_cortex/store.py`).
  The dimension is baked into the `vec0` virtual table at creation time — sqlite-vec's own
  constraint, not a design choice — so changing models means a new table, not a config flag.
- `store_embedding()` rejects any `model_id` other than the pinned one and any vector of the
  wrong dimension, rather than silently mixing incompatible vectors (per
  `resource-readiness.md`'s Model gate: "a mismatch must be detected... not tolerated").
- `embeddings_meta` records `model_id`, `dim`, and `generated_from_hash` per vector — the
  bookkeeping the advanced plan's Phase 3 embedding-model-registry section calls for, scoped down
  to a single pinned model for v1 rather than the full multi-model registry, which is unneeded
  until a second model is actually adopted.

## What wiring a local model back in-process would require

Not attempted here, recorded so it isn't silently forgotten: either (a) confirm this machine's
free RAM has structurally improved beyond the ~200-400MB baseline measured throughout this
project, or (b) run the embedding model as a separate, independently-lifecycled process (not
inside the always-on memory server), so its 270MB is only paid while actively embedding, not for
the server's entire uptime. Revisit this decision if either becomes true — right now, neither is.

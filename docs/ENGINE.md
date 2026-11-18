# SuperCortex engine

The SuperCortex engine (`super_cortex.engine`) is Super-Cortex's own memory backend. It replaces
Supermemory Local behind the same HTTP API, so the MCP server, the studio and the CLI switch
backends by changing one URL. Nothing in the client changes.

| | Supermemory Local | SuperCortex engine |
|---|---|---|
| Default address | `127.0.0.1:6767` | `127.0.0.1:6768` (`SUPER_CORTEX_ENGINE_PORT`) |
| API | `/namespaces`, `/ns/{ns}/document`, `/ns/{ns}/search`, `/ns/{ns}/profile`, … | Same paths and payloads, plus the additions below |
| Search | Vector | Hybrid (FTS5 + sqlite-vec), or `memories`, `combined`, `lexical`, `vector` |
| Learned memories | Opaque | Extracted by "dreaming", every memory grounded in a verbatim quote |
| Extraction model | Hosted | Gemini free tier, or the calling agent's own model (session extraction) |
| Retention | Fixed | Per-namespace policy: `audit`, `standard`, `research` |

## Running it

```bash
uv pip install "super-cortex[engine-local]"      # adds fastembed (BAAI/bge-small-en-v1.5)
export SUPER_CORTEX_ENGINE_API_KEY=...           # required; requests use "Authorization: Bearer <key>"
python -c "from super_cortex.engine.app import main; main()"
```

| Variable | Default | Meaning |
|---|---|---|
| `SUPER_CORTEX_ENGINE_API_KEY` | (required) | Bearer key every request must present |
| `SUPER_CORTEX_ENGINE_DB` | `~/.super-cortex/engine.db` | SQLite database |
| `SUPER_CORTEX_ENGINE_HOST` / `_PORT` | `127.0.0.1` / `6768` | Bind address |
| `SUPER_CORTEX_EMBEDDER` / `SUPER_CORTEX_EMBED_MODEL` | – / `BAAI/bge-small-en-v1.5` | `fastembed` for local embeddings |
| `SUPER_CORTEX_DEFAULT_RETENTION` | `standard` | Preset for namespaces without a policy |
| `SUPER_CORTEX_DREAMING` | `off` | `on` starts the extraction worker |
| `SUPER_CORTEX_DREAM_MODEL` | `gemini-3.5-flash-lite` | Extractor model (Gemini free tier; key in `GEMINI_API_KEY`) |
| `SUPER_CORTEX_DREAM_INTERVAL` | `300` | Seconds between passes |
| `SUPER_CORTEX_DREAM_RPM` / `_DAILY_BUDGET` / `_MAX_REQUESTS_PER_PASS` | `12` / `200` / `30` | Extractor rate limits |

## Dreaming: how memories are learned

Documents are queued when their namespace policy has `dreaming: auto` and their `taskType` is
`memory`. The worker batches queued documents to the extractor, which must return, for each
memory, a verbatim `quote` from its source, a `kind`, an `inference` flag and a `certainty`.
`apply_proposals` then decides what is kept, in this order:

1. **Grounding**: the quote must appear in the source document, or the proposal is rejected (`ungrounded`).
2. **Secret filter**: anything that looks like a credential is rejected.
3. **Dedup / merge / supersede**: near-duplicates of an existing memory attach as extra evidence; a
   contradicting memory supersedes the old one, never silently overwriting it.
4. **Confidence floors**: certainty labels map to scores, and low scores are stored as
   `candidate` (kept, not served).

| `certainty` | Score | Served when not an inference? | Served when an inference? |
|---|---|---|---|
| `certain` | 0.95 | yes | yes |
| `likely` | 0.75 | yes (floor 0.6) | no, candidate (floor 0.8) |
| `uncertain` | 0.4 | no, candidate | no, candidate |

Models asked for a numeric confidence returned 1.0 for everything, which made the floors
meaningless. The extractor now picks a label, and the engine owns the numbers. A numeric
`confidence` is still accepted from extractors that do not send a label.

Memory kinds: `fact`, `preference`, `goal`, `decision`, `rule`, `event` (unknown kinds become `fact`).

### Excluding a namespace from extraction

Set its policy to `dreaming: off`. Its documents are then stored as `skipped` and are never sent to
the extractor, whichever path wrote them:

```bash
curl -X PUT -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"preset":"standard","settings":{"dreaming":"off"}}' http://127.0.0.1:6768/ns/<ns>/policy
```

Do this *before* any client writes a sensitive namespace directly to the engine. A filter in a
sync script only covers the sync path.

### One-time backfill with another extractor

`apply_proposals(store, namespace, docs, related, proposals, extractor_label, stats)` is
extractor-agnostic. A backlog can be extracted by any model (or reviewed by hand) by producing
proposals in the same shape, `{"doc": "D1", "memory", "quote", "kind", "certainty", "inference"}`,
and applying them with `store.mark_dreamed(...)`. Grounding, secret filtering, dedup and the
floors still apply. Label the run (`extractor_label`) so each memory's `generator` records what
produced it.

## Bring your own model: session extraction

Any agent session can do the extraction on its own model instead of the worker calling Gemini:

| Endpoint | Body | Returns |
|---|---|---|
| `POST /ns/{ns}/extraction/claim` | `{"limit": 5, "leaseSeconds": 900}` | `claimId`, `expiresAt`, `instructions`, `prompt`, `responseSchema`, `documents` (`D` labels), `related` (`M` labels); `claimId: null` when nothing is pending |
| `POST /extraction/claims/{id}/submit` | `{"model": "...", "documents": [{"doc": "D1", "memories": [...]}]}` or `{"model", "proposals": [...]}` | the same stats as a worker pass, plus `extractor` and `skipped` |
| `POST /extraction/claims/{id}/release` | none | `{"released": n}`; documents return to the queue without using an attempt |

- A claim leases its documents (`limit` at most 10, lease 60 to 3600 seconds). The worker leases
  its batches too, so a session and the worker never extract the same document.
- Submissions go through `apply_proposals`: grounding, secret filter, dedup, supersede, certainty
  floors. Nothing about acceptance depends on which model answered.
- A document edited after the claim loses its lease and is skipped (`skipped`). Labels are
  renumbered on submit, so `D2` or `M1` can never point at a different document or memory.
- An expired or already-submitted claim is refused with 409. An expired claim's documents are
  back in the queue.
- Memories are stored with `extractor`/`generator` `session:<model>`.
- `dreaming: off` namespaces are never claimable. This is checked against the namespace's
  *current* policy, so documents queued before the policy changed are covered too.

The MCP tools `memory_extraction_claim`/`_submit`/`_release` and the CLI
`super-cortex extract run --with "<agent command>"` wrap these endpoints.

## Profile

`POST /ns/{ns}/profile` returns Supermemory's shape:

- `static`: standing context, meaning current `preference` and `rule` memories.
- `dynamic`: the most recent current memories of every kind, newest first, prefixed
  `[YYYY-MM-DD]`. Each item carries `observedAt`.
- `buckets`: requested kinds (`preferences`, `rules`, `goals`, `decisions`, `events`, `facts`);
  unknown bucket names are listed under `unsupportedBuckets`.

`observedAt` is when the newest attached source was **recorded**, not when extraction ran. It is
taken from the document's `metadata.recordCreatedAt`, then `metadata.createdAt`, if the value is
a date; otherwise it is when the engine received the document. Without this, a backfill would
date months-old facts to the day it ran.

## Moving clients from Supermemory to the engine

The client reads `SUPERMEMORY_URL` and `SUPERMEMORY_API_KEY`. Moving a client means pointing both at
the engine:

1. Run the engine alongside Supermemory, and mirror existing memories into it (for example from
   `provenance.db`, keeping each memory's `id` as the document id so later direct writes upsert
   the same document).
2. Set `dreaming: off` on every namespace that must never reach the extractor (see above).
3. In each client's environment (MCP server entries in agent configs, the studio service), set
   `SUPERMEMORY_URL=http://127.0.0.1:<engine port>` and `SUPERMEMORY_API_KEY=<engine key>`.
   For a systemd unit, use a drop-in `EnvironmentFile=`, which overrides the unit's inline `Environment=`.
4. Verify with the real client: `ping`, `list_namespaces`, `search`, `get_profile`, and an
   ingest/get/delete round-trip on a scratch namespace.
5. Keep Supermemory running until results have been compared on real traffic. To roll back,
   restore the previous `SUPERMEMORY_URL`/`SUPERMEMORY_API_KEY`.

Long-running processes (for example an agent gateway that spawns MCP servers) read their config
at start and need a restart to switch.

## Comparing backends

`super_cortex.retrieval_eval` runs identical queries against both servers (recall@k, MRR), and
`POST /ns/{ns}/profile` can be called on both for a side-by-side profile. On the Phase 2 evaluation
set, engine chunk recall@10 was 0.873 against Supermemory's 0.740, and memory recall@10 was 0.580
against 0.393.

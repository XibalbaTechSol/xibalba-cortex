# Provenance-export verification

This document exists to close Gate 6 of `docs/PRODUCTION_READINESS_PLAN.md`:
"a documented, testable provenance-export verification procedure usable by
someone outside this repo's own operator tooling." It is written for an
auditor or a tenant who has received a bundle but does not run this
repository's own Python package — the algorithm below is specified precisely
enough to reimplement in any language, and `scripts/verify_provenance_export.py`
is a runnable reference implementation using nothing beyond the Python
standard library.

## What a provenance-export bundle is

Cortex can export a bounded set of memories as a signed-shape bundle via the
`memory_export_provenance` MCP tool (`GraphStore.export_memory_bundle` in
`src/xibalba_cortex/store.py`). The bundle has this shape:

```json
{
  "schema_version": "xibalba.provenance_export.v1",
  "count": 2,
  "memory_ids": ["...", "..."],
  "memories": [ /* full memory records, in order */ ],
  "leaf_hashes": ["sha256:...", "sha256:..."],
  "root_hash": "sha256:...",
  "include_forgotten": false,
  "disclaimer": "Commitment proves bundle inclusion under this construction, not truth, authorization, or external finality."
}
```

**Read the disclaimer literally.** The commitment below proves the bundle you
were handed has not been altered, reordered, or truncated since it was
produced — nothing more. It does not prove the underlying memories are true,
that the export was authorized, or that this is the complete set of memories
that exist. Those are separate governance questions outside this document's
scope.

## The commitment algorithm

Given the bundle's `memories` list (in order) and its claimed `leaf_hashes`
and `root_hash`, an independent verifier recomputes both and compares.

### Step 1 — per-memory leaf hash

For each memory object, exactly as it appears in `memories[i]`:

```
canonical(memory) = JSON-encode memory with:
  - object keys sorted lexicographically at every nesting level
  - no whitespace: item separator "," and key separator ":"
  - non-ASCII characters escaped (ensure_ascii=true), not emitted as raw UTF-8

leaf_hash[i] = "sha256:" + hex(SHA-256(UTF-8 bytes of canonical(memory)))
```

This must equal `bundle.leaf_hashes[i]`. If any single memory's canonical
encoding doesn't reproduce its claimed leaf hash, that specific memory's
content has been altered since the bundle was produced — the mismatch
identifies exactly which record (and thus is more informative than a bare
root-hash failure).

### Step 2 — domain-tagged leaves

The domain tag for this export type is the fixed byte string
`xibalba.provenance_export.v1` (UTF-8, no surrounding quotes or trailing
null). For each leaf hash at position `i` (0-indexed):

```
domain_leaf[i] = "sha256:" + hex(SHA-256(
    domain_tag
    + 0x00 + "leaf" + 0x00           (literal bytes: 00 6c 65 61 66 00)
    + i as an 8-byte big-endian unsigned integer
    + raw 32 bytes of leaf_hash[i]   (decode the hex after "sha256:")
))
```

### Step 3 — Merkle fold

Fold `domain_leaf[0..n-1]` pairwise into a single root:

```
fold(level):
    if len(level) == 1: return level[0]
    next_level = []
    for i in 0, 2, 4, ... (step 2):
        if i+1 < len(level):
            a, b = sorted[level[i], level[i+1]]   (byte-sorted, not insertion order)
            next_level.append(SHA-256(raw bytes of a + raw bytes of b))
        else:
            next_level.append(level[i])            (odd node carries through unchanged)
    return fold(next_level)
```

Each element compared and hashed here is the raw 32-byte digest (after
stripping the `sha256:` prefix and hex-decoding), not the hex string itself.
**The pair is sorted before concatenation** — this is not a positional
left/right fold; without this detail a reimplementation will silently produce
the wrong root for any pair whose natural order differs from sorted order.

An empty `memories` list has no root (undefined/absent), matching
`domain_merkle_root`'s own `None` return in that case.

### Step 4 — domain-wrapped root

```
root_hash = "sha256:" + hex(SHA-256(
    domain_tag
    + 0x00 + "root" + 0x00           (literal bytes: 00 72 6f 6f 74 00)
    + raw 32 bytes of the Step 3 result
))
```

This must equal `bundle.root_hash`.

## Running the reference verifier

```bash
python3 scripts/verify_provenance_export.py bundle.json
# or: cat bundle.json | python3 scripts/verify_provenance_export.py
```

The script has zero dependency on the `xibalba_cortex` package — it imports
only `argparse`, `hashlib`, `json`, and `sys` from the standard library, so it
runs on any machine with plain Python 3, no `uv sync`, no venv, no checkout of
this repository beyond the one file. Exit code `0` means the bundle's
`root_hash` was independently confirmed; exit code `1` means it was not, with
a diagnostic identifying whether a specific memory's leaf hash disagreed or
the root-level fold disagreed (which additionally rules out reordering,
truncation, or a directly-edited `root_hash` field even when every individual
leaf still checks out).

## Producing a bundle to test against

```python
from xibalba_cortex.store import GraphStore
store = GraphStore("<profile-home>")
bundle = store.export_memory_bundle(memory_ids=["<id-1>", "<id-2>"])
```

or, over MCP, call the `memory_export_provenance` tool with the same
arguments. Either path returns the identical bundle shape documented above.

## Authorization (correction to an earlier version of this document)

An earlier version of this document claimed `memory_export_provenance` had
"no scope/authorization check, unlike neighboring write-path tools." That
claim was checked against `server.py`'s in-process `@_requires_scope`
decorators only and missed the transport-level auth wrapper — it was wrong,
not just imprecise. In the actual multi-tenant deployment mode
(`--transport streamable-http`), `main()` wraps the whole MCP app in
`BearerTokenAuth` with `required_scopes=("memory:read",)`
(`server.py`'s `main()`), and that middleware rejects every individual HTTP
request — one per tool call, including `memory_export_provenance` — with a
missing, malformed, unknown, or under-scoped token before it ever reaches
tool logic (`auth_middleware.py`'s `BearerTokenAuth.__call__`). Read-path
tools like `memory_export_provenance` correctly inherit that `memory:read`
baseline rather than needing their own redundant per-tool decorator, the
same as `memory_recall`/`memory_get`/`memory_hybrid_retrieve` — none of
which are unscoped either. Write/delete/decide tools additionally require
their own scope on top of that baseline via `@_requires_scope`.

Over `stdio` transport (the local, single-user default), there is
deliberately no bearer-token concept at all — the calling process itself is
the trust boundary, matching how a local Claude Desktop/Cursor MCP
integration works elsewhere. This is the intended, disclosed design, not a
gap.

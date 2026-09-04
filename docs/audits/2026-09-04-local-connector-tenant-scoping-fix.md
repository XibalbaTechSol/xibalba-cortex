# Local-file connector tenant-profile scoping: bug found and fixed

Date: 2026-09-04

Running `docs/operations/connector-drill-runbook.md` §1's local-file connector
isolation drills against a real, properly-provisioned tenant profile (via
`xibalba-cortex-tenant-onboard`) surfaced a real bug, not just an undrilled gap:
three of the four local-file connectors could not run against a tenant profile
at all.

## The bug

`transcript_ingest.py`, `wiki_ingest.py`, and `session_sync.py` each constructed
`GraphStore` directly from the raw `--home` path (`GraphStore(args.home)` /
`GraphStore(source_home)`), never calling `config.load_config(home=...)` first.
`GraphStore.__init__` defaults `profile_id="default"` when not passed explicitly,
so every one of these three connectors always opened a store as the `default`
profile — regardless of what profile a tenant's own `config.yaml` actually
declares. Any profile provisioned by `xibalba_cortex.tenant_onboarding` (which
writes a real, non-default `profile_id` into `config.yaml`) made all three
connectors crash outright:

```
RuntimeError: store profile mismatch: database belongs to 'local-connector-drill', requested 'default'
```

`local_api.py` and `server.py` (the MCP server `codex_mcp_backfill` spawns) were
already correct — both call `load_config(home=...)` then construct
`GraphStore(config.storage.home, profile_id=config.profile_id, ...)`. Only the
three connectors that construct `GraphStore` inline, outside that shared
pattern, had the gap. `codex_mcp_backfill.py` itself never constructs a
`GraphStore` directly — it shells out to the (correct) MCP server — so it was
never affected.

## The fix

Each of the three now calls `load_config(home=args.home)` (or `source_home` for
`session_sync.finalize`) and constructs `GraphStore` from the resolved config,
matching `local_api.py`'s existing pattern exactly. No behavior changes for the
existing single-profile/default-profile callers — `load_config` with no
`config.yaml` present still resolves `profile_id="default"`, identical to the
old hardcoded default.

## Verification (real, not synthetic)

Provisioned two isolated tenant profiles via `xibalba-cortex-tenant-onboard`
and ran each connector against profile A using real fixture data already on
this machine (a real Claude Code transcript, the real `integrity-core` wiki
tree, a second real transcript for session-sync):

| Connector | Run 1 | Run 2 (idempotency) |
|---|---|---|
| `transcript-ingest` | 18 lines processed, 2 memories created | 0 lines processed (resumed from line 18), 0 memories created |
| `wiki-ingest` | 33 pages stored, 0 reused | 0 stored, 33 reused |
| `session-sync` | same session id → 2 memories created | same session id → 0 memories created, same `transcript_memory_id` |

Cross-profile isolation: profile A ended with 39 memories; profile B (never
touched by any of the above) reported exactly 0. `xibalba-cortex-operator
status --home <profile>` was used directly against each profile's real store,
not a mocked call.

Regression tests added: `tests/test_connector_tenant_profile_scoping.py`, one
per fixed connector, each provisioning a real non-default-profile `config.yaml`
and asserting the connector's real entrypoint (`main()` for the first two,
`finalize()` for session_sync) no longer raises the profile-mismatch error.
Full suite (`uv run pytest -q`) passes clean after the fix.

## What this closes

Closes `docs/operations/connector-drill-runbook.md` §1 for all four local-file
connectors: `claude_transcripts`, `hermes_sessions` (via `session_sync`),
`integrity_wiki`, and confirms `codex_mcp` was already correct. Gate 4's
remaining open item is runbook §3 — real Google Drive OAuth evidence, which
needs a real Google account and is an external gate, not something a local
drill can substitute for.

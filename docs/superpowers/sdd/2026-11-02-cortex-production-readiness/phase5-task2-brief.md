# Brief — Phase 5, Task 2: A token reaches its own workspace and no other

Plan: docs/superpowers/plans/2026-11-02-cortex-production-readiness.md
Spec: docs/superpowers/specs/2026-10-26-cortex-account-and-agent-registration-design.md

## Phase 5 — Managed ingestion, and the custom-architecture story

The spec's P5, added 2026-11-02. **The finding that motivates it:** `managed/api.py` serves
25 routes and no ingestion path. The managed Dockerfile runs
`python -m xibalba_cortex.managed.api` alone, so the MCP app is never mounted. The only
route a `managed-api:` token can write to is `POST /api/managed/memories`, which takes
content only and stores every memory `active` (`managed/api.py:376`).

**The shared handler already exists.** `GraphStore.ingest_agent_turn` (`store.py:4923`) is
the one-call primitive; the MCP tool `memory_ingest_agent_turn` (`server.py:865`) and
`provider_bridge.py:128` are both already thin wrappers over it. So "two transports over one
handler" is **a constraint to preserve, not a refactor to perform.** No task below may put
ingestion logic in a transport.

### File Structure

- `src/xibalba_cortex/managed/ingest.py` — **create.** Resolves a bearer token to a
  workspace and calls `GraphStore.ingest_agent_turn`. The only new logic in this phase.
- `src/xibalba_cortex/managed/api.py` — **modify.** Mounts the MCP app; adds one REST route.
  Both delegate.
- `src/xibalba_cortex/grok_adapter.py` — **create.** Identity and policy for the `grok`
  runtime. Calls the same handler; adds no third path.
- `tests/test_managed_ingest.py` — **create.**


### Task 2: A token reaches its own workspace and no other

**Files:**
- Modify: `src/xibalba_cortex/managed/ingest.py`, `tests/test_managed_ingest.py`

- [ ] **Step 1: Write the failing test** — this is Review Focus item 2.

```python
def test_a_token_cannot_write_into_another_workspace(managed_app, api_key_a):
    r = managed_app.post("/api/managed/ingest", headers=bearer(api_key_a),
                         json={**TURN, "workspace_id": "ws-b"})
    assert r.status_code in (401, 403)
    assert managed_app.store("ws-b").session_exchanges("s-1") == []
```

The workspace must come from the **token**, never from the payload. The test passes a
payload workspace precisely to prove it is ignored.

- [ ] **Step 2: Run it and confirm it fails**
- [ ] **Step 3: Derive the workspace from the token record only**, ignoring any
      client-supplied workspace field.
- [ ] **Step 4: Run it and confirm it passes**
- [ ] **Step 5: Prove it can fail** — honour the payload's workspace; confirm this test goes
      red.
- [ ] **Step 6: Commit**


---

## Controller additions

1. **Worktree:** `/mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/account-registration-design`.
   Do not create another; skip `using-git-worktrees` if a sub-skill routes you there.

2. **Task 1 built the route and the fixtures.** Read `tests/conftest.py` as it stands after
   Task 1 rather than creating `managed_app` / `api_key` again. If a fixture you need is
   missing, add it there.

3. **This is the isolation proof, and it must be shown able to fail.** A test that passes
   because the route ignores an unknown body field has measured nothing. Before you claim
   the test works, temporarily make the route trust a `tenant_id` from the payload, confirm
   the test goes red, then revert that mutation. Record both observations in your report.

4. **Auth shape, verified 2026-11-03:** the bearer/API-key path carries no CSRF and no
   `Origin` (the CSRF check in `api.py:126` is gated on `cookie_auth`). Writes still require
   an `Idempotency-Key` header of 8–128 characters or the API returns HTTP 400.

5. **Known adjacent hazard, out of scope here but do not reintroduce it:**
   `server.py:91` holds `_store` as a process global and `:1742` reads the profile from
   `XIBALBA_CORTEX_PROFILE_ID`. That is why managed ingestion must not mount `server.py`'s
   MCP app. Phase 5 Task 3 extends `hosted_connector.py` instead.

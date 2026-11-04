# Brief — Phase 5, Task 1: REST ingestion, scoped to the caller's workspace

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


### Task 1: REST ingestion, scoped to the caller's workspace

**Files:**
- Create: `src/xibalba_cortex/managed/ingest.py`, `tests/test_managed_ingest.py`
- Modify: `src/xibalba_cortex/managed/api.py`

**Interfaces:**
- Consumes: `GraphStore.ingest_agent_turn(external_session_id, *, runtime, prompt, response,
  tool_calls=(), agent_id=None, prompt_id=None, prompt_time=None, response_time=None,
  metadata=None, idempotency_key=None) -> dict`; `verify_token_record` from
  `ingest_tokens`; and the three managed primitives this route must reuse rather than
  reinvent — `service.write_guard(tenant)`, `service.store(tenant)` (per-tenant `GraphStore`
  with path-escape validation and `max_memories` quota) and
  `service.consume(tenant, "writes", request_key=..., fingerprint=...)`. Copy the shape of
  `api.py:368-370`.
- Produces: `ingest_turn(token: str, payload: dict) -> dict`, the route
  `POST /api/managed/ingest`, and the `managed_app` and `api_key` fixtures in
  `tests/conftest.py` (which does not exist yet — create it).

- [ ] **Step 1: Write the failing test**

```python
def test_a_full_turn_lands_with_its_tool_calls(managed_app, api_key):
    r = managed_app.post("/api/managed/ingest", headers=bearer(api_key), json={
        "external_session_id": "s-1", "runtime": "grok",
        "prompt": "hello", "response": "hi",
        "tool_calls": [{"name": "web_search"}],
    })
    assert r.status_code == 200
    stored = managed_app.store("acct-1").session_exchanges("s-1")
    assert stored[0]["tool_call_otel_event_ids"]       # tool calls are committed
    assert managed_app.store("acct-1").verify_chain()["valid"] is True
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/test_managed_ingest.py -v`
Expected: FAIL — 404; the route does not exist.

- [ ] **Step 3: Implement `ingest_turn` and the route.** Resolve the token to its
      `profile_id`, open that profile's store, and call `ingest_agent_turn` with the
      payload. Require the `memory:write` scope the managed key already carries. **Put no
      session, exchange or otel logic here** — the handler owns all of it.
- [ ] **Step 4: Run it and confirm it passes.** Then remove the
      `xfail` marker from Phase 1 Task 3's
      `test_revoking_an_api_key_stops_ingestion_on_the_next_call` and confirm it passes.
- [ ] **Step 5: Prove it can fail** — drop `tool_calls` from the handler call; confirm the
      committed-tool-calls assertion goes red.
- [ ] **Step 6: Meter this route like every other write.** A new route bypasses the limits
      by default, and ingestion is the highest-volume write path in the product — unmetered
      is the expensive failure, and it is reachable by anyone who signs up free. The
      mechanism already exists (see **Execution order**), so this is a call, not a build:
      wrap the write in `service.write_guard(tenant)` and call
      `service.consume(tenant, "writes", request_key=..., fingerprint=...)` exactly as
      `api.py:368-370` does. Write the test that a Free-tier ingest at the
      `writes_per_month` boundary is refused with `LimitExceeded` and the same call succeeds
      on Pro; prove it can fail by removing the `consume` call. Take `request_key` from an
      `Idempotency-Key` header so a retried ingest does not double-charge.
- [ ] **Step 7: Commit**


---

## Controller additions (read these — they override any assumption in the task text)

1. **The worktree already exists** at
   `/mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/account-registration-design`.
   Work there. Do not create another worktree, do not `git clone`, and if a sub-skill
   routes you through `using-git-worktrees`, skip that step.

2. **There is no `tests/conftest.py`.** The fixtures this task names (`managed_app`,
   `api_key`) do not exist. Create them in `tests/conftest.py` as Step 1 of this task.

3. **The shared ingestion handler already exists** — do not write a second one.
   `GraphStore.ingest_agent_turn` at `src/xibalba_cortex/store.py:4923`:
   ```python
   def ingest_agent_turn(self, external_session_id, *, runtime, prompt, response,
       tool_calls=(), agent_id=None, prompt_id=None, prompt_time=None,
       response_time=None, metadata=None, idempotency_key=None) -> dict[str, object]:
   ```
   `server.py:865` (`memory_ingest_agent_turn`) and `provider_bridge.py:128` are both thin
   wrappers over it. Your REST route is a third thin wrapper, not a reimplementation.

4. **Metering and isolation primitives already exist** in
   `src/xibalba_cortex/managed/control.py` — use them, do not duplicate:
   - `service.store(tenant)` at `:216` — returns the tenant-scoped `GraphStore`; it already
     validates the tenant id shape, rejects symlinked roots, rejects path escape, and passes
     `quotas={"max_memories": ...}`.
   - `service.write_guard(tenant)` — serializes per-tenant capacity checks.
   - `service.consume(tenant, meter, *, request_key=None, fingerprint="")` at `:183` — atomic
     counter increment; raises `LimitExceeded`; refuses writes on a read-only entitlement.

5. **Verified 2026-11-03 against a running managed service — the write contract the
   existing routes enforce, which your route must match:**
   - A mutating write **requires an `Idempotency-Key` header of 8–128 characters.**
     Without it the API returns HTTP 400
     `{"error":"Supply an Idempotency-Key containing 8–128 characters"}`. Thread it into
     `consume(..., request_key=...)` and `ingest_agent_turn(..., idempotency_key=...)`.
   - Cookie-authenticated mutations also require a matching `Origin` header and an
     `x-cortex-csrf-token` header (`api.py:99`, `:128`). **Bearer/API-key auth does not
     carry CSRF** — the check at `api.py:126` is gated on `cookie_auth`. Agent ingestion is
     the bearer path, so it must work with no `Origin` and no CSRF token.
   - A read-only entitlement refuses writes with HTTP 403
     `{"error":"Subscription is read-only; existing memories remain available for reading
     and export"}`, while GET reads still return 200. Your route must inherit that, not
     invent a new message.

6. **The tenant comes from the token, never from the payload.** `authenticate` in
   `api.py:102` resolves the principal's `profile_id` from the token record. A `tenant_id`,
   `profile_id`, or `agent_id` field in the request body must not be able to redirect the
   write. Task 2 proves this; do not leave it to Task 2 to also implement.

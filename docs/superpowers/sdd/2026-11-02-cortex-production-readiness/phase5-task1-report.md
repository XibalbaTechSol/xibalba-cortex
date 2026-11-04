# Phase 5 Task 1 report: REST ingestion

Status: DONE_WITH_CONCERNS

Files: src/xibalba_cortex/managed/ingest.py (new), managed/api.py (route + delegate), tests/conftest.py (new: managed_app, api_key), tests/test_managed_ingest.py (new, 10 tests).

TDD: tests written first, run red (all 10 fail, 404 on missing route), implementation restored, green. 10 new tests + tests/test_managed_service.py + test_ingest_tokens + test_ingest_agent_turn all pass.

Mutations (each red, reverted, green):
- drop tool_calls from handler call -> test_a_full_turn_lands_with_its_tool_calls
- remove consume -> free-tier boundary, retried-ingest, read-only tests
- consume without request_key -> retried-ingest-not-charged-twice
- drop Idempotency-Key check -> requires_an_idempotency_key
- drop memory:write check (both route and ingest_turn) -> scope test
- tenant from payload.tenant_id -> workspace_comes_from_the_key
- remove metadata reserved-key filter -> metadata_cannot_shadow
- remove agent_id binding check -> key_cannot_claim_an_agent
- ingest_tokens.py: drop `revoked_at IS NULL` -> revoking_an_api_key test

Decisions / concerns:
1. Brief's test used `verify_chain()` and `exchange["tool_call_otel_event_ids"]`; neither exists in that form (verify_chain takes a memory id; exchanges expose `tool_calls`). Used `verify_exchange_chain("s-1")`, `exchange["tool_calls"]` names, and the response's `tool_call_otel_event_ids`.
2. ingest_turn signature is `ingest_turn(service, token, payload, *, request_key)`, not `(token, payload)`: it needs the ManagedControl. Account-state checks (active/verified/approved, cookie CSRF) live in api.authenticate and are NOT repeated in ingest_turn; the future MCP transport must perform equivalent account checks before calling it.
3. The revocation test does not exist yet as an xfail (plan Phase 1 Task 4 / tests/test_managed_keys.py has not been done), so there was no marker to remove. I added test_revoking_an_api_key_stops_ingestion_on_the_next_call directly in test_managed_ingest.py, passing; Task 4 should reuse or drop its duplicate.
4. Real hole closed: ingest_agent_turn merges caller `metadata` after its own keys, so metadata {"session_id": ...} overwrote source.session_id. ingest_turn strips reserved keys. This arguably belongs in the handler (MCP path has the same exposure on self-hosted); not changed there.
5. agent_id: a body agent_id is accepted only if in the key's bound agent_ids (else 403); absent -> the key's sole bound id, or None. Not specified by the brief.
6. Metering: one turn = one `writes` unit though it stores two memories plus otel rows; the memory quota (max_memories) is mapped to LimitExceeded (429). A quota failure on the second memory leaves the first stored (handler is not transactional).
7. Status 200 returned (per brief test), vs 201 on /memories.
8. Cookie auth takes precedence over bearer in authenticate(); the conftest uses a separate cookie-less client for bearer calls.

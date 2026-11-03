"""API-key revocation at the layer a customer actually touches.

Phase 1 Task 4, and Review Focus item 1: a credential that cannot be withdrawn is live risk.
`ingest_tokens.verify_token_record` already consults `revoked_at`, so this needs no
implementation — it needs a test, because a behaviour that works and is untested is one
refactor away from not working. Phase 5 adds routes that must keep honouring it.

Re-homed here from `test_managed_ingest.py`, where Phase 5 Task 1 wrote it before this file
existed; it is not duplicated there.
"""
TURN = {"external_session_id": "s-1", "runtime": "grok", "prompt": "hello", "response": "hi"}


def bearer(token, key="ingest-key-0001"):
    return {"Authorization": "Bearer " + token, "Idempotency-Key": key}


def test_revoking_an_api_key_stops_ingestion_on_the_next_call(managed_app):
    key_id, token = managed_app.issue_key("acct-1")
    assert managed_app.post("/api/managed/ingest", headers=bearer(token), json=TURN).status_code == 200
    managed_app.revoke_key("acct-1", key_id)
    assert managed_app.post("/api/managed/ingest", headers=bearer(token, "ingest-key-0002"), json=TURN).status_code == 401

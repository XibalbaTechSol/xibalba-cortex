import os
import uuid

import pytest

from xibalba_cortex.accounts import create_account
from xibalba_cortex.managed.config import ManagedConfig
from xibalba_cortex.managed.control import ManagedControl
from xibalba_cortex.managed.storage import SupabaseManagedDbFactory
from starlette.testclient import TestClient
from xibalba_cortex.managed import api as managed_api


@pytest.mark.skipif(not os.environ.get("CORTEX_MANAGED_TEST_DSN"), reason="requires local Supabase Postgres")
def test_auth_subject_migration_and_batch_rollback_preserve_legacy_identity(tmp_path):
    dsn = os.environ["CORTEX_MANAGED_TEST_DSN"]
    config = ManagedConfig(home=tmp_path, storage_backend="supabase", supabase_url="http://127.0.0.1:54321")
    service = ManagedControl(config, db_factory=SupabaseManagedDbFactory(dsn), bootstrap_schema=False,
                             email_sender=lambda *args: None)
    unique = uuid.uuid4().hex
    email = f"legacy-{unique}@example.test"
    tenant_id = "t-" + uuid.uuid4().hex
    account = create_account(service.identity_home, email=email,
                             password="migration-test-password", display_name="Legacy", profile_id=tenant_id)
    with service.db(write=True) as db:
        db.execute("INSERT INTO tenants(id,owner_account_id,created_at) VALUES(?,?,?)",
                   (tenant_id, account["id"], 1))
    auth_subject = str(uuid.uuid4())
    with service.db(write=True) as db:
        db.execute("INSERT INTO auth.users(id,aud,role,email,encrypted_password,confirmed_at,created_at,updated_at) "
                   "VALUES(?, 'authenticated','authenticated',?,'',now(),now(),now())",
                   (auth_subject, email))

    preview = service.migrate_auth_subjects(
        [{"auth_user_id": auth_subject, "legacy_account_id": account["id"]}], batch_id="test-batch")
    assert preview["applied"] is False
    service.migrate_auth_subjects(preview["links"], batch_id="test-batch", apply=True)
    assert service.account_for_auth_subject(auth_subject)["id"] == account["id"]

    class VerifiedTokens:
        def __init__(self, *args, **kwargs): pass
        def verify(self, token):
            assert token == "verified-access-token"
            return {"sub": auth_subject, "exp": 4102444800}

    original_verifier = managed_api.SupabaseAuthVerifier
    managed_api.SupabaseAuthVerifier = VerifiedTokens
    try:
        auth_config = ManagedConfig(home=tmp_path, storage_backend="supabase", identity_backend="supabase_auth",
                                    supabase_url="http://127.0.0.1:54321", public_url="http://localhost:8430")
        app = managed_api.create_app(auth_config, control=service)
        with TestClient(app, base_url=auth_config.public_url) as client:
            exchanged = client.post("/api/managed/auth/session", json={"access_token": "verified-access-token"},
                                    headers={"Origin": auth_config.public_url})
            assert exchanged.status_code == 200, exchanged.text
            assert exchanged.cookies.get(managed_api.COOKIE)
            me = client.get("/api/managed/me")
            assert me.status_code == 200, me.text
            csrf = me.json()["csrf_token"]
            denied = client.post("/api/managed/logout", headers={"Origin": auth_config.public_url,
                                      "X-Cortex-CSRF-Token": "invalid"})
            assert denied.status_code == 403
            logged_out = client.post("/api/managed/logout", headers={"Origin": auth_config.public_url,
                                          "X-Cortex-CSRF-Token": csrf})
            assert logged_out.status_code == 200, logged_out.text
    finally:
        managed_api.SupabaseAuthVerifier = original_verifier

    service.unlink_auth_subject(auth_subject, batch_id="test-batch")
    assert service.account_for_auth_subject(auth_subject) is None
    with service.db() as db:
        tenant = db.execute("SELECT id,owner_account_id,owner_user_id FROM tenants WHERE id=?", (tenant_id,)).fetchone()
        mapping = db.execute("SELECT 1 FROM auth_identity_migrations WHERE auth_user_id=?", (auth_subject,)).fetchone()
    assert tenant["id"] == tenant_id and tenant["owner_account_id"] == account["id"]
    assert tenant["owner_user_id"] is None and mapping is None

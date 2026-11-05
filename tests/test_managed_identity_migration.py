import os
import json
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
    auth_subject = str(uuid.uuid4())
    account = create_account(service.identity_home, email=email,
                             password="migration-test-password", display_name="Legacy", profile_id=tenant_id)
    with service.db(write=True) as db:
        db.execute("INSERT INTO auth.users(id,aud,role,email,encrypted_password,confirmed_at,created_at,updated_at) "
                   "VALUES(?, 'authenticated','authenticated',?,'',now(),now(),now())",
                   (auth_subject, email))
        db.execute("INSERT INTO tenants(id,owner_account_id,owner_user_id,created_at) VALUES(?,?,?,?)",
                   (tenant_id, account["id"], auth_subject, 1))
        db.execute("INSERT INTO tenant_memberships(tenant_id,user_id,role) VALUES(?,?,'member')",
                   (tenant_id, auth_subject))

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

    assert service.rollback_auth_subject_batch("test-batch") == 1
    assert service.account_for_auth_subject(auth_subject) is None
    with service.db() as db:
        tenant = db.execute("SELECT id,owner_account_id,owner_user_id FROM tenants WHERE id=?", (tenant_id,)).fetchone()
        mapping = db.execute("SELECT 1 FROM auth_identity_migrations WHERE auth_user_id=?", (auth_subject,)).fetchone()
        membership = db.execute("SELECT role FROM tenant_memberships WHERE tenant_id=? AND user_id=?",
                                 (tenant_id, auth_subject)).fetchone()
    assert tenant["id"] == tenant_id and tenant["owner_account_id"] == account["id"]
    assert str(tenant["owner_user_id"]) == auth_subject and mapping is None
    assert membership["role"] == "member"


@pytest.mark.skipif(not os.environ.get("CORTEX_MANAGED_TEST_DSN"), reason="requires local Supabase Postgres")
def test_rollback_removes_owner_link_and_membership_created_by_migration(tmp_path):
    dsn = os.environ["CORTEX_MANAGED_TEST_DSN"]
    config = ManagedConfig(home=tmp_path, storage_backend="supabase", supabase_url="http://127.0.0.1:54321")
    service = ManagedControl(config, db_factory=SupabaseManagedDbFactory(dsn), bootstrap_schema=False)
    unique = uuid.uuid4().hex
    tenant_id, auth_subject = "t-" + unique, str(uuid.uuid4())
    account = create_account(service.identity_home, email=f"new-{unique}@example.test",
                             password="migration-test-password", display_name="New legacy", profile_id=tenant_id)
    with service.db(write=True) as db:
        db.execute("INSERT INTO auth.users(id,aud,role,email,encrypted_password,confirmed_at,created_at,updated_at) "
                   "VALUES(?, 'authenticated','authenticated',?,'',now(),now(),now())",
                   (auth_subject, f"new-{unique}@example.test"))
        db.execute("INSERT INTO tenants(id,owner_account_id,created_at) VALUES(?,?,?)",
                   (tenant_id, account["id"], 1))

    service.migrate_auth_subjects(
        [{"auth_user_id": auth_subject, "legacy_account_id": account["id"]}],
        batch_id="created-links-batch", apply=True,
    )
    with service.db() as db:
        assert str(db.execute("SELECT owner_user_id FROM tenants WHERE id=?", (tenant_id,)).fetchone()["owner_user_id"]) == auth_subject
        assert db.execute("SELECT role FROM tenant_memberships WHERE tenant_id=? AND user_id=?",
                          (tenant_id, auth_subject)).fetchone()["role"] == "owner"

    assert service.rollback_auth_subject_batch("created-links-batch") == 1
    with service.db() as db:
        tenant = db.execute("SELECT owner_account_id,owner_user_id FROM tenants WHERE id=?", (tenant_id,)).fetchone()
        membership = db.execute("SELECT 1 FROM tenant_memberships WHERE tenant_id=? AND user_id=?",
                                 (tenant_id, auth_subject)).fetchone()
    assert tenant["owner_account_id"] == account["id"] and tenant["owner_user_id"] is None
    assert membership is None
    assert service.account_for_auth_subject(auth_subject) is None


@pytest.mark.skipif(not os.environ.get("CORTEX_MANAGED_TEST_DSN"), reason="requires local Supabase Postgres")
def test_supabase_new_account_provisioning_is_idempotent_and_rollback_safe(tmp_path):
    dsn = os.environ["CORTEX_MANAGED_TEST_DSN"]
    config = ManagedConfig(home=tmp_path, storage_backend="supabase", identity_backend="supabase_auth",
                           supabase_url="http://127.0.0.1:54321", allow_signup=True)
    service = ManagedControl(config, db_factory=SupabaseManagedDbFactory(dsn), bootstrap_schema=False,
                             email_sender=lambda *args: None)
    subject, email = str(uuid.uuid4()), f"provision-{uuid.uuid4().hex}@example.test"
    with service.db(write=True) as db:
        db.execute(
            "INSERT INTO auth.users(id,aud,role,email,encrypted_password,confirmed_at,raw_user_meta_data,created_at,updated_at) "
            "VALUES(?, 'authenticated','authenticated',?,'',now(),?::jsonb,now(),now())",
            (subject, email, json.dumps({"full_name": "Provisioned User"})),
        )

    first = service.provision_auth_subject(subject, batch_id="provision-test:" + subject)
    second = service.provision_auth_subject(subject, batch_id="provision-test:" + subject)
    assert first["id"] == "supabase:" + subject
    assert first["email"] == email and first["display_name"] == "Provisioned User"
    assert second["profile_id"] == first["profile_id"]
    with service.db() as db:
        membership = db.execute(
            "SELECT role FROM tenant_memberships WHERE tenant_id=? AND user_id=?",
            (first["profile_id"], subject),
        ).fetchone()
    assert membership["role"] == "owner"

    batch_id = "provision-test:" + subject
    assert service.rollback_auth_subject_batch(batch_id) == 1
    restored = service.provision_auth_subject(subject, batch_id=batch_id)
    assert restored["profile_id"] == first["profile_id"]


@pytest.mark.skipif(not os.environ.get("CORTEX_MANAGED_TEST_DSN"), reason="requires local Supabase Postgres")
def test_supabase_new_account_never_links_a_legacy_profile_by_email(tmp_path):
    dsn = os.environ["CORTEX_MANAGED_TEST_DSN"]
    config = ManagedConfig(home=tmp_path, storage_backend="supabase", identity_backend="supabase_auth",
                           supabase_url="http://127.0.0.1:54321", allow_signup=True)
    service = ManagedControl(config, db_factory=SupabaseManagedDbFactory(dsn), bootstrap_schema=False,
                             email_sender=lambda *args: None)
    subject, email = str(uuid.uuid4()), f"collision-{uuid.uuid4().hex}@example.test"
    create_account(service.identity_home, email=email, password="migration-test-password",
                   display_name="Legacy profile", profile_id="t-" + uuid.uuid4().hex)
    with service.db(write=True) as db:
        db.execute(
            "INSERT INTO auth.users(id,aud,role,email,encrypted_password,confirmed_at,created_at,updated_at) "
            "VALUES(?, 'authenticated','authenticated',?,'',now(),now(),now())",
            (subject, email),
        )

    with pytest.raises(PermissionError, match="explicitly migrated by account ID"):
        service.provision_auth_subject(subject)

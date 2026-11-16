import pytest
from super_cortex.models import TenantPlan, TenantRecord
from super_cortex.store import ProvenanceStore


def test_tenant_lifecycle(tmp_path):
    db_file = tmp_path / "test_tenants.db"
    store = ProvenanceStore(db_file)

    # 1. Verify default seeded tenants
    tenants = store.list_tenants()
    assert len(tenants) >= 3
    tenant_ids = {t["id"] for t in tenants}
    assert "tenant_xibalba_core" in tenant_ids
    assert "tenant_dev_sandbox" in tenant_ids

    # 2. Create custom tenant
    t_rec = TenantRecord(
        id="tenant_acme_corp",
        name="Acme Agentics Inc",
        plan=TenantPlan.PRO.value,
        rate_limit_rpm=180,
        daily_quota_requests=15000,
        metadata={"industry": "Autonomous Finance"},
    )
    saved = store.save_tenant(t_rec)
    assert saved.id == "tenant_acme_corp"

    fetched = store.get_tenant("tenant_acme_corp")
    assert fetched is not None
    assert fetched["name"] == "Acme Agentics Inc"
    assert fetched["plan"] == "pro"

    # 3. Create scoped API key
    key_rec, raw_key = store.create_tenant_key(
        tenant_id="tenant_acme_corp",
        label="Production Trading Swarm",
        scopes=["read:graph", "write:memory", "exec:deterministic"],
        rate_limit_rpm=180,
    )
    assert raw_key.startswith("sc_live_")
    assert key_rec["tenant_id"] == "tenant_acme_corp"
    assert key_rec["label"] == "Production Trading Swarm"
    assert key_rec["requests_count"] == 0

    # 4. Authenticate and consume key with token savings
    auth_result = store.verify_and_consume_key(raw_key, cost_tokens=2500)
    assert auth_result is not None
    assert auth_result["tenant_name"] == "Acme Agentics Inc"
    assert auth_result["scopes"] == ["read:graph", "write:memory", "exec:deterministic"]

    # Verify usage metrics incremented
    keys = store.list_tenant_keys(tenant_id="tenant_acme_corp")
    assert len(keys) == 1
    assert keys[0]["requests_count"] == 1
    assert keys[0]["zero_inference_tokens_saved"] == 2500
    assert keys[0]["estimated_savings_dollars"] > 0

    # 5. Revoke key
    revoked = store.revoke_tenant_key(key_rec["key_id"])
    assert revoked is True

    # Should fail authentication after revocation
    auth_after_revoke = store.verify_and_consume_key(raw_key)
    assert auth_after_revoke is None

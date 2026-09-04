import pytest

from xibalba_cortex.config import load_config
from xibalba_cortex.ingest_tokens import verify_token_record
from xibalba_cortex.store import GraphStore
from xibalba_cortex.tenant_onboarding import provision_tenant


def test_provisions_isolated_profile_with_expiring_operator_token(tmp_path):
    result = provision_tenant(tmp_path, "tenant-a", ttl_hours=24, max_memories=10)
    home = tmp_path / "tenant-a"
    config = load_config(home=home)
    principal = verify_token_record(home, result["token"])
    assert config.profile_id == "tenant-a"
    assert config.storage.home == home
    assert config.quotas.max_memories == 10
    assert principal["profile_id"] == "tenant-a"
    assert principal["expires_at"] is not None
    assert principal["scopes"] == ["memory:delete", "memory:read", "memory:write", "proposal:decide"]


def test_two_tenants_cannot_read_or_influence_each_other(tmp_path):
    provision_tenant(tmp_path, "tenant-a")
    provision_tenant(tmp_path, "tenant-b")
    store_a = GraphStore(tmp_path / "tenant-a", profile_id="tenant-a")
    store_b = GraphStore(tmp_path / "tenant-b", profile_id="tenant-b")
    try:
        secret = store_a.store_memory("tenant-a-only evidence", source={"kind": "isolation-test"})
        with pytest.raises(KeyError):
            store_b.get_memory(secret["id"])
        assert store_b.search("tenant-a-only", limit=10) == []
        assert store_b.list_inference_tasks() == []
        with pytest.raises(RuntimeError, match="store profile mismatch"):
            GraphStore(tmp_path / "tenant-a", profile_id="tenant-b")
    finally:
        store_a.close()
        store_b.close()


def test_rejects_path_traversal_and_duplicate_tenant(tmp_path):
    with pytest.raises(ValueError, match="tenant_id"):
        provision_tenant(tmp_path, "../escape")
    provision_tenant(tmp_path, "tenant-a")
    with pytest.raises(FileExistsError, match="already exists"):
        provision_tenant(tmp_path, "tenant-a")

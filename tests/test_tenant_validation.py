from xibalba_cortex.tenant_onboarding import provision_tenant
from xibalba_cortex.tenant_validation import validate_profiles


def test_concurrent_multi_profile_validation(tmp_path):
    provision_tenant(tmp_path, "tenant-a", max_memories=100)
    provision_tenant(tmp_path, "tenant-b", max_memories=100)
    report = validate_profiles([tmp_path / "tenant-a", tmp_path / "tenant-b"], workers_per_profile=2, writes_per_worker=5)
    assert report["passed"] is True
    assert report["profiles"]["tenant-a"]["writes"] == 10
    assert report["profiles"]["tenant-b"]["writes"] == 10
    assert report["profiles"]["tenant-a"]["foreign_matches"] == 0
    assert report["profiles"]["tenant-b"]["foreign_matches"] == 0

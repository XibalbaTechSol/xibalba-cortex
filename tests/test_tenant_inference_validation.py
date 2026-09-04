from xibalba_cortex.tenant_inference_validation import validate_process_inference
from xibalba_cortex.tenant_onboarding import provision_tenant


def test_separate_process_inference_isolation_and_completion(tmp_path):
    provision_tenant(tmp_path, "tenant-a", max_memories=100)
    provision_tenant(tmp_path, "tenant-b", max_memories=100)
    report = validate_process_inference([tmp_path / "tenant-a", tmp_path / "tenant-b"], processes_per_profile=2, tasks_per_process=2)
    assert report["passed"] is True
    assert report["profiles"]["tenant-a"]["completed_tasks"] == 4
    assert report["profiles"]["tenant-b"]["completed_tasks"] == 4
    assert report["profiles"]["tenant-a"]["foreign_tasks_visible"] == 0
    assert report["profiles"]["tenant-b"]["foreign_tasks_visible"] == 0

import os

import pytest

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


@pytest.mark.skipif(
    os.environ.get("XIBALBA_RUN_SUSTAINED_INFERENCE_DRILL") != "1",
    reason="sustained-load drill is opt-in (~15-20s); set XIBALBA_RUN_SUSTAINED_INFERENCE_DRILL=1 to run it",
)
def test_sustained_load_no_longer_deadlocks_on_queue_drain_order(tmp_path):
    """Regression test for a real, reproduced deadlock: at 200 tasks/process
    (8 worker processes, 1600 total tasks), validate_process_inference used to
    hang for its entire timeout, every time, three separate runs. Root cause
    (found via heartbeat instrumentation, not guessed): the harness joined
    every worker process BEFORE draining result_queue. multiprocessing.Queue
    writes through a background feeder thread into a bounded OS pipe -- the
    Python docs explicitly warn that a child which has put() enough data will
    not finish exiting until it's flushed, so joining first can deadlock
    exactly this way. One worker was caught mid-exit with a live
    QueueFeederThread while every worker's own heartbeat showed its actual
    task loop, queue put, and store.close() had ALL already succeeded --
    proving the hang was never in application logic, only in the harness's
    join-before-drain ordering. Fixed by draining the queue first (which does
    not require the producer to have exited), then joining. This test is the
    scale that reliably reproduced the deadlock before the fix; kept opt-in
    since ~15-20s is too slow for the default fast suite."""
    provision_tenant(tmp_path, "sustained-a", max_memories=None)
    provision_tenant(tmp_path, "sustained-b", max_memories=None)
    report = validate_process_inference(
        [tmp_path / "sustained-a", tmp_path / "sustained-b"],
        processes_per_profile=4, tasks_per_process=200, timeout_seconds=90.0,
    )
    assert report["passed"] is True
    assert report["timed_out_pids"] == []
    assert all(code == 0 for code in report["exit_codes"])
    assert report["profiles"]["sustained-a"]["completed_tasks"] == 800
    assert report["profiles"]["sustained-b"]["completed_tasks"] == 800

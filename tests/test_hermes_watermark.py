from __future__ import annotations

import time

from xibalba_cortex.hermes_watermark import record_invocation, staleness_report, status


def test_record_invocation_then_status_reports_success(tmp_path):
    db_path = tmp_path / "watermark.sqlite3"
    record_invocation("post_llm_call", session_id="s1", success=True, db_path=db_path)

    rows = status(db_path=db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row.hook_name == "post_llm_call"
    assert row.last_session_id == "s1"
    assert row.total_invocations == 1
    assert row.total_failures == 0
    assert row.consecutive_failures == 0
    assert row.last_success is True
    assert row.last_error is None


def test_record_invocation_tracks_failure_and_consecutive_streak(tmp_path):
    db_path = tmp_path / "watermark.sqlite3"
    record_invocation("post_tool_call", session_id="s1", success=False, error="boom-1", db_path=db_path)
    record_invocation("post_tool_call", session_id="s1", success=False, error="boom-2", db_path=db_path)

    row = status(db_path=db_path)[0]
    assert row.total_invocations == 2
    assert row.total_failures == 2
    assert row.consecutive_failures == 2
    assert row.last_success is False
    assert row.last_error == "boom-2"


def test_consecutive_failures_resets_on_a_later_success(tmp_path):
    db_path = tmp_path / "watermark.sqlite3"
    record_invocation("post_tool_call", session_id="s1", success=False, error="boom", db_path=db_path)
    record_invocation("post_tool_call", session_id="s1", success=True, db_path=db_path)

    row = status(db_path=db_path)[0]
    assert row.total_invocations == 2
    assert row.total_failures == 1
    assert row.consecutive_failures == 0
    assert row.last_success is True


def test_staleness_report_distinguishes_never_seen_from_stale(tmp_path):
    db_path = tmp_path / "watermark.sqlite3"
    now = time.time()
    record_invocation("post_llm_call", session_id="s1", success=True, db_path=db_path, now=now - 10)

    report = staleness_report(
        ["post_llm_call", "post_tool_call"], max_age_seconds=60, db_path=db_path, now=now
    )
    assert report["post_llm_call"]["seen"] is True
    assert report["post_llm_call"]["stale"] is False

    assert report["post_tool_call"]["seen"] is False
    assert report["post_tool_call"]["stale"] is True
    assert report["post_tool_call"]["age_seconds"] is None


def test_staleness_report_flags_a_hook_that_went_quiet(tmp_path):
    db_path = tmp_path / "watermark.sqlite3"
    now = time.time()
    record_invocation("post_llm_call", session_id="s1", success=True, db_path=db_path, now=now - 3700)

    report = staleness_report(["post_llm_call"], max_age_seconds=3600, db_path=db_path, now=now)
    assert report["post_llm_call"]["seen"] is True
    assert report["post_llm_call"]["stale"] is True

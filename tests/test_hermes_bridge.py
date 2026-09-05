import json
import subprocess
import sys

from xibalba_cortex.hermes_watermark import status as watermark_status
from xibalba_cortex.store import GraphStore


def _run_bridge(hook_name, kwargs, env):
    return subprocess.run(
        [sys.executable, "-m", "xibalba_cortex.hermes_bridge", hook_name],
        input=json.dumps(kwargs), text=True, capture_output=True, env=env, timeout=30,
    )


def test_bridge_dispatches_post_llm_call_to_the_env_selected_store(tmp_path, monkeypatch):
    import os
    env = dict(os.environ)
    env["XIBALBA_CORTEX_HOME"] = str(tmp_path / "graph")

    result = _run_bridge(
        "post_llm_call",
        {"session_id": "s1", "turn_id": "turn-1", "user_message": "hi", "assistant_response": "hello"},
        env,
    )
    assert result.returncode == 0, result.stderr

    store = GraphStore(tmp_path / "graph")
    contents = {m["content"] for m in store.session_memories("s1")}
    assert contents == {"hi", "hello"}
    store.close()

    # Real, subprocess-produced watermark evidence -- not just a successful exit code, a durable
    # record that this exact hook fired and succeeded (hermes_watermark.py).
    watermark_db = tmp_path / "graph" / "hermes_hook_watermark.sqlite3"
    rows = watermark_status(db_path=watermark_db)
    assert len(rows) == 1
    assert rows[0].hook_name == "post_llm_call"
    assert rows[0].last_session_id == "s1"
    assert rows[0].last_success is True
    assert rows[0].total_invocations == 1


def test_bridge_rejects_unknown_hook_name(tmp_path):
    import os
    env = dict(os.environ)
    env["XIBALBA_CORTEX_HOME"] = str(tmp_path / "graph")

    result = _run_bridge("not_a_real_hook", {"session_id": "s1"}, env)
    assert result.returncode == 1
    assert "unknown hook" in result.stderr

    # The failure is durably recorded, not only printed to stderr that nothing ever reads in the
    # real fire-and-forget deployment -- the exact gap this module closes.
    watermark_db = tmp_path / "graph" / "hermes_hook_watermark.sqlite3"
    rows = watermark_status(db_path=watermark_db)
    assert len(rows) == 1
    assert rows[0].hook_name == "not_a_real_hook"
    assert rows[0].last_success is False
    assert "unknown hook" in rows[0].last_error


def test_bridge_records_watermark_failure_when_store_construction_crashes(tmp_path):
    """A real, naturally-occurring crash (not a fabricated exception): the GraphStore's own
    db_path exists as a directory instead of a file, so sqlite3.connect() genuinely fails with
    'unable to open database file'. Before hermes_watermark.py, this crash's only trace was a
    traceback on a subprocess's stderr that a fire-and-forget Hermes caller never reads."""
    import os

    graph_home = tmp_path / "graph"
    graph_home.mkdir()
    (graph_home / "graph-memory.sqlite3").mkdir()  # a directory where GraphStore expects a file

    env = dict(os.environ)
    env["XIBALBA_CORTEX_HOME"] = str(graph_home)

    result = _run_bridge("post_llm_call", {"session_id": "s1"}, env)
    assert result.returncode != 0

    watermark_db = graph_home / "hermes_hook_watermark.sqlite3"
    rows = watermark_status(db_path=watermark_db)
    assert len(rows) == 1
    assert rows[0].hook_name == "post_llm_call"
    assert rows[0].last_success is False
    assert "store construction failed" in rows[0].last_error


def test_bridge_requires_exactly_one_argument(tmp_path):
    import os
    env = dict(os.environ)
    env["XIBALBA_CORTEX_HOME"] = str(tmp_path / "graph")

    result = subprocess.run(
        [sys.executable, "-m", "xibalba_cortex.hermes_bridge"],
        input="{}", text=True, capture_output=True, env=env, timeout=30,
    )
    assert result.returncode == 2

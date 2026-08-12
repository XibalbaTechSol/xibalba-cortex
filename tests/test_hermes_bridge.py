import json
import subprocess
import sys

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


def test_bridge_rejects_unknown_hook_name(tmp_path):
    import os
    env = dict(os.environ)
    env["XIBALBA_CORTEX_HOME"] = str(tmp_path / "graph")

    result = _run_bridge("not_a_real_hook", {"session_id": "s1"}, env)
    assert result.returncode == 1
    assert "unknown hook" in result.stderr


def test_bridge_requires_exactly_one_argument(tmp_path):
    import os
    env = dict(os.environ)
    env["XIBALBA_CORTEX_HOME"] = str(tmp_path / "graph")

    result = subprocess.run(
        [sys.executable, "-m", "xibalba_cortex.hermes_bridge"],
        input="{}", text=True, capture_output=True, env=env, timeout=30,
    )
    assert result.returncode == 2

from argparse import Namespace
import json

from xibalba_graph.operator import readiness, run_command
from xibalba_graph.store import GraphStore


def _args(command, home, **kwargs):
    return Namespace(command=command, home=str(home), **kwargs)


def test_operator_readiness_reports_disk_and_memory_thresholds(tmp_path):
    result = readiness(tmp_path / "graph", min_disk_bytes=1, min_memory_bytes=1)

    assert result["ready"] is True
    assert result["checks"]["disk"]["ok"] is True
    assert result["checks"]["memory"]["mode"] == "warn"


def test_operator_status_backup_restore_and_verify_memory(tmp_path):
    home = tmp_path / "graph"
    store = GraphStore(home)
    memory = store.store_memory(
        "Operator command coverage.",
        source={"kind": "direct_user", "locator": "operator://test"},
        status="confirmed",
    )
    store.close()

    status = run_command(_args("status", home))
    assert status["integrity_check"] == "ok"

    backup_path = tmp_path / "snapshot.sqlite3"
    backup = run_command(_args("backup", home, destination=str(backup_path)))
    assert backup["integrity_check"] == "ok"

    verify = run_command(_args("verify-memory", home, memory_id=memory["id"]))
    assert verify["valid"] is True

    store = GraphStore(home)
    store.store_memory(
        "This post-backup write must be removed by restore.",
        source={"kind": "direct_user", "locator": "operator://after-backup"},
        status="confirmed",
    )
    store.close()

    restored = run_command(_args("restore", home, source=str(backup_path)))
    assert restored["integrity_check"] == "ok"

    store = GraphStore(home)
    assert store.search("post-backup") == []
    assert store.get_memory(memory["id"])["content"] == "Operator command coverage."
    store.close()


def test_operator_verify_session_and_integrity_links(tmp_path):
    home = tmp_path / "graph"
    store = GraphStore(home)
    store.record_model_exchange(
        "operator-session",
        user_prompt="Question",
        model_response="Answer",
        context=[],
        runtime="codex",
    )
    store.close()

    verify = run_command(_args("verify-session", home, session_id="operator-session"))
    assert verify["valid"] is True

    links = run_command(_args("integrity-links", home, limit=5))
    assert links["states"]["unlinked"] >= 2


def test_operator_verify_integrity_link(tmp_path):
    home = tmp_path / "graph"
    store = GraphStore(home)
    memory = store.store_memory(
        "Operator Integrity link.",
        source={"kind": "direct_user", "locator": "operator://integrity-link"},
        status="confirmed",
    )
    node_id = "0x" + "e" * 64
    dag_dir = tmp_path / "vault" / "did_integrity_operator"
    dag_dir.mkdir(parents=True)
    (dag_dir / "memory_nodes.jsonl").write_text(
        json.dumps(
            {
                "node_id": node_id,
                "kind": "memory",
                "content_hash": GraphStore._integrity_memory_content_hash("Operator Integrity link."),
            }
        )
        + "\n"
    )
    store.close()

    result = run_command(
        _args(
            "verify-integrity-link",
            home,
            memory_id=memory["id"],
            node_id=node_id,
            dag_home=str(tmp_path / "vault"),
            agent_id=None,
        )
    )
    assert result["verification_state"] == "hash_match_local"
    assert result["truth_authorization_completeness"] is False

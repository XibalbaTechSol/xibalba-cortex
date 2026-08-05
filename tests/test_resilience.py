"""Task 9 acceptance gaps: concurrency, crash recovery, and profile isolation.

These exercise scenarios reasoned about but never actually verified -- notably the Devil's
Advocate review in docs/architecture/advanced-memory.md section 3.1, which argued SQLite WAL is
sufficient for this system's deployment model without a test backing that argument up.
"""
import multiprocessing
import os
import sqlite3
import threading

from xibalba_graph.store import GraphStore


def _crash_mid_write(db_path: str, memory_id: str) -> None:
    """Run in a separate process: open a connection, start a write, never commit, hard-exit
    without cleanup -- os._exit skips atexit/finalizers, the closest in-process analog to a
    kill. The OS reliably releases the file lock when the process actually terminates, which
    a same-process `del` does not guarantee (see the test this replaced).
    """
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("UPDATE memories SET status = 'forgotten' WHERE id = ?", (memory_id,))
    os._exit(1)


def test_concurrent_writes_from_two_separate_connections_do_not_corrupt(tmp_path):
    """Two independent GraphStore instances (two real SQLite connections, not one connection
    shared across threads) writing to the same database concurrently -- the actual scenario a
    second Hermes session or a CLI-plus-MCP-server combination would produce.
    """
    home = tmp_path / "graph"
    store_a = GraphStore(home)
    store_b = GraphStore(home)  # separate connection, same db_path

    errors: list[Exception] = []
    written_ids: list[str] = []
    write_lock = threading.Lock()

    def write_from(store: GraphStore, label: str, count: int) -> None:
        for i in range(count):
            try:
                memory = store.store_memory(
                    f"Concurrent write {label}-{i}",
                    source={"kind": "direct_user", "locator": f"hermes://session/{label}"},
                    status="confirmed",
                )
                with write_lock:
                    written_ids.append(memory["id"])
            except Exception as exc:  # noqa: BLE001 -- want to see any failure, not just ours
                errors.append(exc)

    threads = [
        threading.Thread(target=write_from, args=(store_a, "a", 15)),
        threading.Thread(target=write_from, args=(store_b, "b", 15)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == []
    assert len(written_ids) == 30
    assert len(set(written_ids)) == 30  # no id collisions

    status = store_a.status()
    assert status["integrity_check"] == "ok"

    store_a.close()
    store_b.close()


def test_uncommitted_transaction_left_by_a_crash_does_not_corrupt_committed_data(tmp_path):
    """Simulates a process crash mid-write: an open transaction with no COMMIT, connection
    dropped without cleanup. A fresh connection must recover WAL correctly -- prior committed
    data intact, integrity_check clean -- without needing this store's own code to do anything
    special, because that recovery guarantee is SQLite WAL's job, not application code's.
    """
    store = GraphStore(tmp_path / "graph")
    survivor = store.store_memory(
        "Committed before the crash.",
        source={"kind": "direct_user", "locator": "hermes://session/crash"},
        status="confirmed",
    )
    store.close()

    db_path = str(tmp_path / "graph" / "graph-memory.sqlite3")
    process = multiprocessing.Process(target=_crash_mid_write, args=(db_path, survivor["id"]))
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 1  # confirms the crash actually happened, not skipped silently

    reopened = GraphStore(tmp_path / "graph")
    status = reopened.status()
    assert status["integrity_check"] == "ok"

    recovered = reopened.get_memory(survivor["id"])
    assert recovered["status"] == "confirmed"  # the uncommitted UPDATE must not have applied
    assert recovered["content"] == "Committed before the crash."
    reopened.close()


def test_two_profiles_are_fully_isolated_on_disk(tmp_path):
    """Two GraphStore instances under different homes share nothing -- separate files, separate
    permissions, and a write to one is invisible to the other.
    """
    home_a = tmp_path / "profile-a" / "xibalba-graph"
    home_b = tmp_path / "profile-b" / "xibalba-graph"
    store_a = GraphStore(home_a)
    store_b = GraphStore(home_b)

    assert store_a.db_path != store_b.db_path
    assert os.stat(home_a).st_mode & 0o777 == 0o700
    assert os.stat(home_b).st_mode & 0o777 == 0o700

    store_a.store_memory(
        "Only visible in profile A.",
        source={"kind": "direct_user", "locator": "hermes://session/a"},
        status="confirmed",
    )

    assert len(store_a.search("Only visible in profile A")) == 1
    assert store_b.search("Only visible in profile A") == []

    store_a.close()
    store_b.close()

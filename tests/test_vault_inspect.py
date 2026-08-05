import json

from eth_hash.auto import keccak

from xibalba_graph.vault_inspect import inspect_leaf


def _write_leaf(vault_dir, *, task_id="task-1", commit_sha="abc123", test_result_hash="deadbeef", timestamp=1000):
    preimage = "|".join(
        ["integrity.vault.commit.v1", task_id, commit_sha, test_result_hash, str(timestamp)]
    ).encode("utf-8")
    leaf_hash = "0x" + keccak(preimage).hex()
    leaf = {
        "kind": "commit",
        "task_id": task_id,
        "commit_sha": commit_sha,
        "test_result_hash": test_result_hash,
        "timestamp": timestamp,
        "leaf_hash": leaf_hash,
    }
    leaves_path = vault_dir / "leaves.jsonl"
    with leaves_path.open("a") as f:
        f.write(json.dumps(leaf) + "\n")
    return leaf_hash


def test_missing_vault_reports_not_found(tmp_path):
    result = inspect_leaf("0xdoesnotmatter", tmp_path / "no-such-vault")
    assert result == {"found": False, "anchored": False, "leaf": None, "anchor": None}


def test_finds_leaf_and_recomputes_hash_but_reports_unanchored(tmp_path):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    leaf_hash = _write_leaf(vault_dir)

    result = inspect_leaf(leaf_hash, vault_dir)
    assert result["found"] is True
    assert result["anchored"] is False
    assert result["recomputed_hash_matches"] is True
    assert result["leaf"]["task_id"] == "task-1"
    assert result["anchor"] is None


def test_finds_leaf_covered_by_a_later_anchor(tmp_path):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    leaf_hash = _write_leaf(vault_dir)
    _write_leaf(vault_dir, task_id="task-2")  # a second leaf pushes leaves_through past index 0

    anchor = {
        "root": "0xabc",
        "tx_hash": "0xdef",
        "epoch": 1,
        "leaves_through": 2,
        "anchored_at": 2000,
    }
    with (vault_dir / "anchors.jsonl").open("a") as f:
        f.write(json.dumps(anchor) + "\n")

    result = inspect_leaf(leaf_hash, vault_dir)
    assert result["found"] is True
    assert result["anchored"] is True
    assert result["anchor"]["tx_hash"] == "0xdef"


def test_detects_tampered_leaf_hash_via_recomputation(tmp_path):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    leaf_hash = _write_leaf(vault_dir)

    # Tamper with the stored leaf content without touching leaf_hash -- the recomputed hash
    # from the (now-inconsistent) fields must no longer match the stored hash.
    leaves_path = vault_dir / "leaves.jsonl"
    leaves = [json.loads(line) for line in leaves_path.read_text().splitlines()]
    leaves[0]["commit_sha"] = "tampered"
    leaves_path.write_text("\n".join(json.dumps(leaf) for leaf in leaves) + "\n")

    result = inspect_leaf(leaf_hash, vault_dir)
    assert result["found"] is True
    assert result["recomputed_hash_matches"] is False

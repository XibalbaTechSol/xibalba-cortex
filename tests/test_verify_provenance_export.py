"""Gate 6 evidence: scripts/verify_provenance_export.py is a real, standalone
verifier -- run as a subprocess (not imported), proving it genuinely has no
dependency on this package, against a bundle produced by a real store."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

from xibalba_cortex.store import GraphStore

SCRIPT = Path(__file__).parent.parent / "scripts" / "verify_provenance_export.py"


def _run_verifier(bundle_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(bundle_path)],
        capture_output=True, text=True,
    )


def _real_bundle(tmp_path: Path) -> dict:
    store = GraphStore(tmp_path / "graph")
    m1 = store.store_memory("The backbone protocol computes AIS in exactly one place.", source={"kind": "test"}, status="confirmed")
    m2 = store.store_memory("Provenance export commits via a domain-separated Merkle root.", source={"kind": "test"}, status="confirmed")
    bundle = store.export_memory_bundle(memory_ids=[m1["id"], m2["id"]])
    store.close()
    return bundle


def test_verifier_confirms_a_real_untampered_bundle(tmp_path):
    bundle = _real_bundle(tmp_path)
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(bundle))

    result = _run_verifier(bundle_path)

    assert result.returncode == 0, result.stderr
    assert "VERIFIED" in result.stdout
    assert bundle["root_hash"] in result.stdout


def test_verifier_rejects_a_tampered_memory(tmp_path):
    bundle = _real_bundle(tmp_path)
    tampered = copy.deepcopy(bundle)
    tampered["memories"][0]["content"] = tampered["memories"][0]["content"] + " TAMPERED"
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(tampered))

    result = _run_verifier(bundle_path)

    assert result.returncode == 1
    assert "leaf 0" in result.stderr
    assert "does not match" in result.stderr


def test_verifier_rejects_a_tampered_root_hash(tmp_path):
    bundle = _real_bundle(tmp_path)
    tampered = copy.deepcopy(bundle)
    tampered["root_hash"] = "sha256:" + "0" * 64
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(tampered))

    result = _run_verifier(bundle_path)

    assert result.returncode == 1
    assert "root_hash" in result.stderr
    assert "does not match" in result.stderr


def test_verifier_reads_from_stdin(tmp_path):
    bundle = _real_bundle(tmp_path)

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(bundle), capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "VERIFIED" in result.stdout

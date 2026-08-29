"""Regression coverage for kernel_bridge.py's default deployments-file resolution.

No live devnet/chain coverage here (submit_kernel_intent needs a real anvil + kernel-bridge
testbed, out of scope for this repo's unit tests) -- just the pure path-math bug that let
the default silently point one directory too high (parents[4] instead of parents[3]), which
went undetected because it was always masked by an XIBALBA_KERNEL_BRIDGE_DEPLOYMENTS override
in whatever shell actually ran it.
"""
from __future__ import annotations

from pathlib import Path

from xibalba_cortex import kernel_bridge


def test_default_deployments_path_resolves_to_sibling_integrity_core(monkeypatch):
    monkeypatch.delenv("XIBALBA_KERNEL_BRIDGE_DEPLOYMENTS", raising=False)
    monkeypatch.delenv("XIBALBA_KERNEL_BRIDGE_PRIVATE_KEY", raising=False)

    captured: dict[str, Path] = {}

    def fake_load_deployments(path: Path) -> dict:
        captured["path"] = path
        raise FileNotFoundError(str(path))  # short-circuit before any network call

    monkeypatch.setattr(kernel_bridge, "_load_deployments", fake_load_deployments)

    try:
        kernel_bridge.submit_kernel_intent(recipient="0x" + "0" * 40, value_wei=1)
    except FileNotFoundError:
        pass

    package_root = Path(kernel_bridge.__file__).resolve().parents[2]  # xibalba-cortex/
    expected = package_root.parent / "integrity-core" / "deployments.local.kernel-bridge.json"
    assert captured["path"] == expected

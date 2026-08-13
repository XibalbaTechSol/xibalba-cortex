from __future__ import annotations

from pathlib import Path

import yaml

from xibalba_cortex.hermes_worker import WORKER_PROFILE_NAME
from xibalba_cortex.providers import NativeHarnessInferenceProvider

_PROFILE_ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "scripts" / "worker-profile"


def _load_worker_config() -> dict:
    return yaml.safe_load((_PROFILE_ARTIFACT_DIR / "config.yaml").read_text())


def test_worker_profile_config_has_no_plugins_and_disables_memory():
    config = _load_worker_config()
    # `plugins` must be entirely absent, not an empty list -- an empty `plugins: {enabled: []}`
    # is a different (and weaker) statement than omitting the key; omission is what the
    # default-config fallback treats as "no plugins attached" for this profile.
    assert "plugins" not in config
    assert config["memory"]["memory_enabled"] is False
    assert config["memory"]["user_profile_enabled"] is False


def test_worker_profile_config_restricts_tools_to_an_explicit_allowlist():
    config = _load_worker_config()
    servers = config["mcp_servers"]
    assert set(servers.keys()) == {"xibalba_cortex"}
    include = servers["xibalba_cortex"]["tools"]["include"]
    assert set(include) == {
        "memory_claim_inference_task",
        "memory_evidence_bundle",
        "memory_complete_inference_task",
        "memory_inference_subagent_manifest",
    }
    # None of these are read/write memory tools -- the leak vector this profile exists to close.
    assert "memory_recall" not in include
    assert "memory_hybrid_retrieve" not in include
    assert "memory_forget" not in include
    assert "memory_supersede" not in include


def test_worker_profile_soul_has_no_mission_hierarchy_content():
    soul = (_PROFILE_ARTIFACT_DIR / "SOUL.md").read_text()
    for leaked_term in ("Xibalba Solutions LLC", "fractional COO", "Integrity Protocol", "xibalba-quant"):
        assert leaked_term not in soul


def test_native_harness_provider_invokes_hermes_with_profile_flag():
    captured = {}

    def fake_runner(command, *, prompt, timeout):
        captured["command"] = command
        return '{"ok": true}'

    provider = NativeHarnessInferenceProvider(harness="hermes", profile_name=WORKER_PROFILE_NAME, runner=fake_runner)
    result = provider.infer("do the thing")

    assert result == '{"ok": true}'
    assert captured["command"] == ["hermes", "-z", "do the thing", "-p", WORKER_PROFILE_NAME]


def test_native_harness_provider_omits_profile_flag_when_unset():
    captured = {}

    def fake_runner(command, *, prompt, timeout):
        captured["command"] = command
        return "{}"

    provider = NativeHarnessInferenceProvider(harness="hermes", runner=fake_runner)
    provider.infer("do the thing")

    assert captured["command"] == ["hermes", "-z", "do the thing"]

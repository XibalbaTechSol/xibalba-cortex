from pathlib import Path

from xibalba_cortex.operator import build_parser, run_command


def test_operator_config_show_returns_redacted_effective_config(tmp_path):
    (tmp_path / "config.yaml").write_text("mode: hybrid\nremote:\n  api_key: private\n")
    args = build_parser().parse_args(["--home", str(tmp_path), "config", "show"])

    result = run_command(args)

    assert result["mode"] == "hybrid"
    assert result["remote"]["api_key"] == "[REDACTED]"


def test_operator_doctor_reports_provider_mode(tmp_path):
    args = build_parser().parse_args(["--home", str(tmp_path), "doctor"])

    result = run_command(args)

    assert result["mode"] == "local"
    assert result["canonical_store"] == "sqlite"
    assert result["inference_provider"] == "native_harness"
    assert result["embedding_provider"] == "local"
    assert result["connectors"]["webhook"]["state"] == "implemented"
    assert result["connectors"]["google_drive"]["state"] == "optional_dependency"

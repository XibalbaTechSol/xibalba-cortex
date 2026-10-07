"""viewer/COVERAGE.md must account for every MCP tool and documented HTTP route.

The point is that a capability cannot become "hidden" by being added without a decision: a new tool
in server.py or a new route in local_api.py's docstring fails here until scripts/ui_coverage.py
says which console surface covers it, or why it is deliberately not a console feature.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ui_coverage.py"


def _load():
    spec = importlib.util.spec_from_file_location("ui_coverage", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_tool_and_documented_route_is_classified():
    assert _load().problems() == []


def test_the_committed_coverage_file_is_current():
    module = _load()
    assert module.OUTPUT.read_text() == module.render(), "run: python scripts/ui_coverage.py --write"


def test_withheld_tools_are_the_ones_that_would_hand_a_browser_a_server_path_or_act_outward():
    module = _load()
    withheld = {tool for tool, (status, _) in module.TOOLS.items() if status == "withheld"}
    assert withheld == {
        "memory_attach", "memory_backup", "memory_backup_reconcile", "memory_vault_inspect",
        "memory_verify_integrity_link", "memory_anchor_session_root",
    }

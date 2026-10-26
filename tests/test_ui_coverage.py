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


def test_no_tool_is_withheld_from_the_console_for_want_of_a_route():
    """A tool was once withheld because it took a server path or acted outward and no safe browser route
    existed. Each now has one: the browser sends an id, a hash or bytes, the server owns every path,
    and outward actions are confirmed and named. If a tool is withheld again it must be decided here."""
    module = _load()
    withheld = {tool for tool, (status, _) in module.TOOLS.items() if status == "withheld"}
    assert withheld == set()

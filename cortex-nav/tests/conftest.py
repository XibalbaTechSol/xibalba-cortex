from __future__ import annotations

import json
from pathlib import Path

import pytest

from cortex_nav.graph import ToolCallGraph, load_toolgraph

FIXTURES = Path(__file__).parent / "fixtures"
TOY_PATH = FIXTURES / "toy_toolgraph.json"


@pytest.fixture
def toy_spec() -> dict:
    return json.loads(TOY_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def toy() -> ToolCallGraph:
    return load_toolgraph(TOY_PATH)

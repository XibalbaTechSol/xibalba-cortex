import pytest
from starlette.testclient import TestClient

from super_cortex.api import create_app
from super_cortex.config import SuperCortexConfig
from super_cortex.causal import compute_probabilistic_causal_chain


def test_probabilistic_causal_chain_math():
    turns = [
        {
            "prompt_text": "Investigate why timeline view is freezing and build right click menu",
            "thinking_text": "The timeline has 16k DOM marks causing layout thrash, need to paginate and add context menu",
            "tool_calls": [
                {"name": "read_file", "args": {"path": "viewer/index.html"}},
                {"name": "edit_file", "args": {"path": "viewer/index.html"}},
            ],
            "response_text": "Timeline view optimized and dedicated context menu attached.",
            "created_at": "2026-11-19T03:00:00Z",
            "agent_id": "agy",
        }
    ]
    res = compute_probabilistic_causal_chain("test_session_1", turns)
    assert res["status"] == "ok"
    assert res["turn_count"] == 1
    assert len(res["nodes"]) == 5  # Intent + Delib + Action1 + Action2 + State
    assert len(res["edges"]) == 4

    metrics = res["metrics"]
    assert 0.0 < metrics["causal_determinism"] <= 1.0
    assert metrics["total_actions"] == 2
    assert metrics["bayesian_confidence"] in ("HIGH", "MODERATE", "EXPLORATORY")
    assert metrics["average_entropy_bits"] >= 0.0


def test_api_causal_analysis_endpoint(tmp_path):
    cfg = SuperCortexConfig(db_path=tmp_path / "provenance.db")
    app = create_app(config=cfg)
    client = TestClient(app)

    # Empty / fallback call
    res = client.get("/api/causal/analysis")
    assert res.status_code == 200
    d = res.json()
    assert "nodes" in d
    assert "metrics" in d

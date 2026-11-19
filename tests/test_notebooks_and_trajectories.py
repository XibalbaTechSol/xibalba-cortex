"""
Tests for Phase 3 & 4: Packaged Jupyter Notebooks & Trajectory Fine-Tuning Dataset Hub.
Verifies SFT, DPO, GRPO dataset generation, JSONL serialization, and dynamic .ipynb generation.
"""

import json
import pytest
from starlette.testclient import TestClient

from super_cortex.api import create_app
from super_cortex.config import SuperCortexConfig
from super_cortex.memory import SuperCortex
from super_cortex.trajectories import (
    export_dataset_jsonl,
    export_dpo_dataset,
    export_grpo_dataset,
    export_sft_dataset,
    extract_reasoning_trajectories,
    generate_jupyter_notebook,
)


@pytest.fixture
def traj_cortex(tmp_path):
    db_file = tmp_path / "test_trajectories.db"
    cfg = SuperCortexConfig(db_path=str(db_file))
    cortex = SuperCortex(config=cfg)

    # Scopes & Agents
    cortex.create_scope("shared", "Shared Memory Fabric", "shared")
    cortex.create_scope("agent:quant", "Quant Research Scope", "single_agent")
    cortex.register_agent("quant", "Hermes Quant", "hermes", "agent:quant")

    # Record two multi-turn exchanges with chain-of-thought and tool calls
    cortex.record_exchange(
        session_id="sess_trading_01",
        prompt_text="Optimize portfolio Sharpe ratio under drawdown constraint <= 8%.",
        response_text="Allocated 65% to risk-free treasury proxies and 35% to mean-reverting momentum alpha.",
        thinking_text="Applying Markowitz mean-variance optimization with Kuhn-Tucker constraints on max drawdown.",
        tool_calls=[{"name": "solve_convex_qp", "args": {"drawdown_max": 0.08}}],
        actor="did:integrity:quant-bot",
    )

    cortex.record_exchange(
        session_id="sess_trading_01",
        prompt_text="Evaluate stability of the covariance matrix estimation.",
        response_text="Ledoit-Wolf shrinkage estimator converged with optimal shrinkage intensity delta=0.24.",
        thinking_text="Sample covariance is ill-conditioned (N/T > 0.5). Applying Ledoit-Wolf analytic shrinkage towards constant correlation target.",
        tool_calls=[{"name": "ledoit_wolf_shrinkage", "args": {"target": "constant_correlation"}}],
        actor="did:integrity:quant-bot",
    )

    return cortex


def test_extract_trajectories(traj_cortex):
    trajs = extract_reasoning_trajectories(traj_cortex.store)
    assert len(trajs) == 2
    assert trajs[0]["session_id"] == "sess_trading_01"
    assert len(trajs[0]["tool_calls"]) == 1
    assert "Markowitz" in trajs[0]["thinking_text"]
    assert trajs[0]["reward_score"] >= 0.70


def test_export_sft_dataset(traj_cortex):
    sft = export_sft_dataset(traj_cortex.store)
    assert len(sft) == 2
    sample = sft[0]
    assert sample["id"].startswith("sft_")
    assert len(sample["messages"]) == 2
    assert sample["messages"][0]["role"] == "user"
    assert sample["messages"][1]["role"] == "assistant"
    assert "thinking" in sample["messages"][1]
    assert "tool_calls" in sample["messages"][1]


def test_export_dpo_dataset(traj_cortex):
    dpo = export_dpo_dataset(traj_cortex.store)
    assert len(dpo) == 2
    sample = dpo[0]
    assert sample["id"].startswith("dpo_")
    assert "chosen" in sample
    assert "rejected" in sample
    assert sample["chosen"]["reward"] > sample["rejected"]["reward"]
    assert sample["margin"] > 0.0
    assert sample["chosen"]["thinking"] != ""
    assert sample["rejected"]["thinking"] == ""


def test_export_grpo_dataset(traj_cortex):
    grpo = export_grpo_dataset(traj_cortex.store)
    assert len(grpo) == 2
    sample = grpo[0]
    assert sample["id"].startswith("grpo_")
    assert len(sample["candidates"]) >= 2
    assert sample["candidates"][0]["is_verified"] is True
    assert sample["candidates"][1]["is_verified"] is False


def test_export_dataset_jsonl(traj_cortex):
    sft = export_sft_dataset(traj_cortex.store)
    jsonl_str = export_dataset_jsonl(sft)
    lines = [line for line in jsonl_str.strip().split("\n") if line]
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert "messages" in parsed


def test_generate_jupyter_notebook():
    for tmpl in ("spectral", "gnn", "trajectories"):
        nb = generate_jupyter_notebook(template=tmpl, host_url="http://127.0.0.1:4174")
        assert nb["nbformat"] == 4
        assert len(nb["cells"]) >= 2
        assert any(c["cell_type"] == "code" for c in nb["cells"])
        assert any(c["cell_type"] == "markdown" for c in nb["cells"])


def test_cortex_sdk_methods(traj_cortex):
    sft = traj_cortex.export_sft_dataset()
    assert len(sft) == 2

    dpo = traj_cortex.export_dpo_dataset()
    assert len(dpo) == 2

    grpo = traj_cortex.export_grpo_dataset()
    assert len(grpo) == 2

    nb = traj_cortex.generate_jupyter_notebook("spectral")
    assert nb["metadata"]["super_cortex"]["template"] == "spectral"


def test_http_trajectory_and_notebook_endpoints(traj_cortex):
    app = create_app(config=traj_cortex.config)
    client = TestClient(app)

    # 1. /api/export/trajectories?format=sft
    r_sft = client.get("/api/export/trajectories?format=sft")
    assert r_sft.status_code == 200
    assert r_sft.json()["format"] == "sft"
    assert len(r_sft.json()["dataset"]) == 2

    # 2. /api/export/trajectories?format=dpo&as_jsonl=true
    r_dpo_jsonl = client.get("/api/export/trajectories?format=dpo&as_jsonl=true")
    assert r_dpo_jsonl.status_code == 200
    assert "attachment" in r_dpo_jsonl.headers.get("content-disposition", "")
    lines = [l for l in r_dpo_jsonl.text.strip().split("\n") if l]
    assert len(lines) == 2

    # 3. /api/export/trajectories?format=grpo
    r_grpo = client.get("/api/export/trajectories?format=grpo")
    assert r_grpo.status_code == 200
    assert r_grpo.json()["format"] == "grpo"

    # 4. /api/export/notebook?template=gnn
    r_nb = client.get("/api/export/notebook?template=gnn")
    assert r_nb.status_code == 200
    assert "attachment" in r_nb.headers.get("content-disposition", "")
    nb_dict = r_nb.json()
    assert nb_dict["nbformat"] == 4

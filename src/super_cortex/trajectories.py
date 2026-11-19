"""
Agent Reasoning Trajectory Fine-Tuning Dataset Hub & Dynamic Jupyter Notebook Generator.
Provides:
1. SFT (Supervised Fine-Tuning) ChatML datasets with chain-of-thought thinking traces.
2. DPO (Direct Preference Optimization) paired chosen/rejected trajectory datasets.
3. GRPO (Group Relative Policy Optimization / RLVR) verified reward datasets.
4. Dynamic Jupyter Notebook (.ipynb v4) generator pre-wired to Super-Cortex endpoints.
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any

from super_cortex.store import SuperCortexStore

logger = logging.getLogger("super_cortex.trajectories")


def extract_reasoning_trajectories(
    store: SuperCortexStore,
    scope: str = "all",
) -> list[dict[str, Any]]:
    """
    Extract all raw turn traces, thoughts, responses, and tool calls from the store.
    """
    results: list[dict[str, Any]] = []

    with store._get_conn() as conn:
        query = """
            SELECT 
                exchange_id, session_id, prompt_text, prompt_hash,
                response_text, response_hash, thinking_text, tool_calls_json,
                context_hashes_json, turn_hash, parent_hash, created_at,
                scope_id, agent_id
            FROM exchanges
        """
        params: list[Any] = []
        if scope != "all":
            query += " WHERE scope_id = ?"
            params.append(scope)

        query += " ORDER BY created_at ASC"
        rows = conn.execute(query, params).fetchall()

        for r in rows:
            d = dict(r)
            try:
                d["tool_calls"] = json.loads(d["tool_calls_json"]) if d["tool_calls_json"] else []
            except Exception:
                d["tool_calls"] = []

            try:
                d["context_hashes"] = json.loads(d["context_hashes_json"]) if d["context_hashes_json"] else []
            except Exception:
                d["context_hashes"] = []

            # Compute quality/reward score r in [0.0, 1.0]
            score = 0.2
            if d.get("thinking_text") and len(d["thinking_text"].strip()) > 10:
                score += 0.35
            if len(d.get("response_text", "").strip()) > 20:
                score += 0.25
            if d["tool_calls"]:
                score += 0.20
            d["reward_score"] = round(min(1.0, score), 4)

            results.append(d)

    return results


def export_sft_dataset(
    store: SuperCortexStore,
    scope: str = "all",
) -> list[dict[str, Any]]:
    """
    Export reasoning traces formatted for Supervised Fine-Tuning (SFT).
    Adheres to the ChatML / HuggingFace standard with thinking and tool calling.
    """
    trajectories = extract_reasoning_trajectories(store, scope=scope)
    dataset: list[dict[str, Any]] = []

    for t in trajectories:
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": t["response_text"],
        }
        if t.get("thinking_text"):
            assistant_msg["thinking"] = t["thinking_text"]
        if t.get("tool_calls"):
            assistant_msg["tool_calls"] = t["tool_calls"]

        dataset.append({
            "id": f"sft_{t['exchange_id']}",
            "session_id": t["session_id"],
            "exchange_id": t["exchange_id"],
            "scope": t.get("scope_id") or "shared",
            "agent_id": t.get("agent_id") or "agent:default",
            "messages": [
                {"role": "user", "content": t["prompt_text"]},
                assistant_msg,
            ],
            "reward": t["reward_score"],
            "created_at": t["created_at"],
        })

    return dataset


def export_dpo_dataset(
    store: SuperCortexStore,
    scope: str = "all",
) -> list[dict[str, Any]]:
    """
    Export reasoning traces formatted for Direct Preference Optimization (DPO).
    Pairs high-reward completions (with detailed thinking & tool actions) against
    lower-reward completions (omitting reasoning traces or ungrounded responses).
    """
    trajectories = extract_reasoning_trajectories(store, scope=scope)
    dpo_pairs: list[dict[str, Any]] = []

    for t in trajectories:
        # Chosen completion: full grounded response with thinking and tool actions
        chosen: dict[str, Any] = {
            "role": "assistant",
            "content": t["response_text"],
            "thinking": t.get("thinking_text", ""),
            "tool_calls": t.get("tool_calls", []),
            "reward": t["reward_score"],
        }

        # Rejected completion: shallow response stripped of chain-of-thought or truncated
        shallow_content = t["response_text"]
        if len(shallow_content) > 100:
            shallow_content = shallow_content[:80] + "..."
        rejected: dict[str, Any] = {
            "role": "assistant",
            "content": shallow_content,
            "thinking": "",  # Empty reasoning trace
            "tool_calls": [],
            "reward": round(max(0.1, t["reward_score"] * 0.35), 4),
        }

        margin = round(chosen["reward"] - rejected["reward"], 4)

        dpo_pairs.append({
            "id": f"dpo_{t['exchange_id']}",
            "session_id": t["session_id"],
            "prompt": t["prompt_text"],
            "chosen": chosen,
            "rejected": rejected,
            "margin": margin,
            "scope": t.get("scope_id") or "shared",
        })

    return dpo_pairs


def export_grpo_dataset(
    store: SuperCortexStore,
    scope: str = "all",
) -> list[dict[str, Any]]:
    """
    Export reasoning traces formatted for Group Relative Policy Optimization (GRPO / RLVR).
    Includes candidate completions with explicit reward verification flags.
    """
    trajectories = extract_reasoning_trajectories(store, scope=scope)
    grpo_samples: list[dict[str, Any]] = []

    for t in trajectories:
        is_verified = t["reward_score"] >= 0.70
        grpo_samples.append({
            "id": f"grpo_{t['exchange_id']}",
            "session_id": t["session_id"],
            "prompt": t["prompt_text"],
            "scope": t.get("scope_id") or "shared",
            "candidates": [
                {
                    "completion": t["response_text"],
                    "thinking": t.get("thinking_text", ""),
                    "tool_calls": t.get("tool_calls", []),
                    "reward": t["reward_score"],
                    "is_verified": is_verified,
                },
                {
                    "completion": "I am not sure.",
                    "thinking": "No reasoning provided.",
                    "tool_calls": [],
                    "reward": 0.05,
                    "is_verified": False,
                },
            ],
        })

    return grpo_samples


def export_dataset_jsonl(records: list[dict[str, Any]]) -> str:
    """
    Serialize a list of dataset records into RFC-compliant newline-delimited JSON (JSONL).
    """
    output = io.StringIO()
    for rec in records:
        output.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return output.getvalue()


def generate_jupyter_notebook(
    template: str = "spectral",
    host_url: str = "http://127.0.0.1:4174",
    scope: str = "all",
) -> dict[str, Any]:
    """
    Generate a dynamic, executable Jupyter Notebook (.ipynb v4) pre-configured
    with Super-Cortex API endpoints and ready-to-run data science workflows.
    Templates:
    - 'spectral': Spectral graph theory, Laplacian eigenvalues, Louvain community analysis.
    - 'gnn': PyTorch Geometric dataset ingestion and GCN node classification.
    - 'trajectories': SFT & DPO reasoning trajectory dataset analysis and reward histograms.
    """
    template = template.lower()

    if template == "gnn":
        cells = [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# Super-Cortex // PyTorch Geometric (PyG) GNN Node Classification\n",
                    "This notebook fetches the live 3D neural knowledge manifold from Super-Cortex,\n",
                    "converts it into a `torch_geometric.data.Data` graph tensor, and trains a Graph Convolutional Network (GCN).\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# 1. Install & import required libraries\n",
                    "# pip install torch torch_geometric httpx polars matplotlib\n",
                    "import httpx\n",
                    "import torch\n",
                    "import torch.nn.functional as F\n",
                    "from torch_geometric.data import Data\n",
                    "from torch_geometric.nn import GCNConv\n",
                    "\n",
                    f"CORTEX_HOST = '{host_url}'\n",
                    f"SCOPE = '{scope}'\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# 2. Ingest graph tensors directly from Super-Cortex REST API\n",
                    "resp = httpx.get(f'{CORTEX_HOST}/api/export/pyg', params={'scope': SCOPE})\n",
                    "data_spec = resp.json()\n",
                    "\n",
                    "print(f\"Ingested {data_spec['num_nodes']} nodes and {data_spec['num_edges']} edges.\")\n",
                    "\n",
                    "# Construct PyG Data object\n",
                    "edge_index = torch.tensor(data_spec['edge_index'], dtype=torch.long)\n",
                    "y = torch.tensor(data_spec['y'], dtype=torch.long)\n",
                    "num_classes = len(data_spec['node_types'])\n",
                    "\n",
                    "# Initialize node feature matrix X (one-hot or degree + degree centralities)\n",
                    "num_nodes = data_spec['num_nodes']\n",
                    "x = torch.eye(num_nodes) if num_nodes <= 1000 else torch.randn(num_nodes, 32)\n",
                    "\n",
                    "pyg_graph = Data(x=x, edge_index=edge_index, y=y)\n",
                    "print(pyg_graph)\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# 3. Define 2-layer Graph Convolutional Network (GCN)\n",
                    "class CortexGCN(torch.nn.Module):\n",
                    "    def __init__(self, in_channels, hidden_channels, out_channels):\n",
                    "        super().__init__()\n",
                    "        self.conv1 = GCNConv(in_channels, hidden_channels)\n",
                    "        self.conv2 = GCNConv(hidden_channels, out_channels)\n",
                    "\n",
                    "    def forward(self, x, edge_index):\n",
                    "        x = self.conv1(x, edge_index)\n",
                    "        x = F.relu(x)\n",
                    "        x = F.dropout(x, p=0.2, training=self.training)\n",
                    "        x = self.conv2(x, edge_index)\n",
                    "        return F.log_softmax(x, dim=1)\n",
                    "\n",
                    "model = CortexGCN(x.size(1), 16, num_classes)\n",
                    "optimizer = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=5e-4)\n",
                    "\n",
                    "# Training loop (30 epochs)\n",
                    "model.train()\n",
                    "for epoch in range(1, 31):\n",
                    "    optimizer.zero_grad()\n",
                    "    out = model(pyg_graph.x, pyg_graph.edge_index)\n",
                    "    loss = F.nll_loss(out, pyg_graph.y)\n",
                    "    loss.backward()\n",
                    "    optimizer.step()\n",
                    "    if epoch % 5 == 0:\n",
                    "        print(f'Epoch {epoch:02d} | Loss: {loss.item():.4f}')\n",
                ],
            },
        ]
    elif template == "trajectories":
        cells = [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# Super-Cortex // AI Reasoning Trajectory & Fine-Tuning Dataset Hub\n",
                    "Inspects Super-Cortex multi-agent reasoning traces, thinking paths, and DPO margin distributions.\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "import httpx\n",
                    "import json\n",
                    "import polars as pl\n",
                    "\n",
                    f"CORTEX_HOST = '{host_url}'\n",
                    f"SCOPE = '{scope}'\n",
                    "\n",
                    "# Fetch SFT and DPO datasets from Super-Cortex\n",
                    "sft_resp = httpx.get(f'{CORTEX_HOST}/api/export/trajectories', params={'format': 'sft', 'scope': SCOPE})\n",
                    "dpo_resp = httpx.get(f'{CORTEX_HOST}/api/export/trajectories', params={'format': 'dpo', 'scope': SCOPE})\n",
                    "\n",
                    "sft_data = sft_resp.json()['dataset']\n",
                    "dpo_data = dpo_resp.json()['dataset']\n",
                    "\n",
                    "print(f\"Loaded {len(sft_data)} SFT samples and {len(dpo_data)} DPO pairs.\")\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# Convert DPO pairs to Polars DataFrame for reward analysis\n",
                    "df = pl.DataFrame([\n",
                    "    {\n",
                    "        'id': p['id'],\n",
                    "        'chosen_reward': p['chosen']['reward'],\n",
                    "        'rejected_reward': p['rejected']['reward'],\n",
                    "        'margin': p['margin'],\n",
                    "        'has_thinking': bool(p['chosen'].get('thinking')),\n",
                    "    }\n",
                    "    for p in dpo_data\n",
                    "])\n",
                    "print(df.describe())\n",
                ],
            },
        ]
    else:  # 'spectral'
        cells = [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# Super-Cortex // Spectral Graph Theory & Topological Manifold Analytics\n",
                    "Fetches live graph components and quantitative scorecard from Super-Cortex,\n",
                    "analyzing the Graph Laplacian spectrum, Fiedler algebraic connectivity, and Louvain communities.\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "import httpx\n",
                    "import networkx as nx\n",
                    "import polars as pl\n",
                    "\n",
                    f"CORTEX_HOST = '{host_url}'\n",
                    f"SCOPE = '{scope}'\n",
                    "\n",
                    "# 1. Fetch full topological summary\n",
                    "summary = httpx.get(f'{CORTEX_HOST}/api/analytics/summary', params={'scope': SCOPE}).json()\n",
                    "print(\"=== SUPER-CORTEX GRAPH TOPOLOGY SCORECARD ===\")\n",
                    "print(f\"Nodes: {summary['node_count']} | Edges: {summary['edge_count']}\")\n",
                    "print(f\"Modularity Q: {summary['modularity']:.4f}\")\n",
                    "print(f\"Algebraic Connectivity λ₂: {summary['algebraic_connectivity']:.6f}\")\n",
                    "print(f\"Average Clustering Coefficient: {summary['avg_clustering_coefficient']:.4f}\")\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# 2. Ingest into NetworkX DiGraph\n",
                    "nx_data = httpx.get(f'{CORTEX_HOST}/api/export/networkx', params={'format': 'json', 'scope': SCOPE}).json()\n",
                    "G = nx.node_link_graph(nx_data, edges='links')\n",
                    "print(f\"Constructed NetworkX graph: {G}\")\n",
                ],
            },
        ]

    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3 (ipykernel)",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "version": "3.12",
            },
            "super_cortex": {
                "version": "0.1.0",
                "template": template,
                "scope": scope,
                "host_url": host_url,
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }

"""Tests for Formal Mathematics of Graphs Engine."""

from __future__ import annotations

import numpy as np
import pytest
from xibalba_cortex.graph_math import compute_formal_graph_math


def test_empty_graph():
    res = compute_formal_graph_math([], [])
    assert res["node_count"] == 0
    assert res["edge_count"] == 0
    assert res["density"] == 0.0
    assert res["adjacency_matrix"] == []


def test_formal_graph_mathematics_metrics():
    # Construct a known 4-node graph:
    # 0 -> 1, 1 -> 2, 2 -> 3, 3 -> 0, 0 -> 2
    nodes = [
        {"id": "node_0", "label": "Imatinib"},
        {"id": "node_1", "label": "BCR-ABL1"},
        {"id": "node_2", "label": "CML"},
        {"id": "node_3", "label": "Apoptosis"},
    ]
    edges = [
        {"source": "node_0", "target": "node_1", "weight": 1.0},
        {"source": "node_1", "target": "node_2", "weight": 1.0},
        {"source": "node_2", "target": "node_3", "weight": 1.0},
        {"source": "node_3", "target": "node_0", "weight": 1.0},
        {"source": "node_0", "target": "node_2", "weight": 1.0},
    ]

    math_res = compute_formal_graph_math(nodes, edges)

    assert math_res["node_count"] == 4
    assert math_res["edge_count"] == 5

    # Check Adjacency Matrix
    adj = np.array(math_res["adjacency_matrix"])
    assert adj.shape == (4, 4)
    assert adj[0, 1] == 1.0
    assert adj[0, 2] == 1.0
    assert adj[1, 2] == 1.0

    # Check Combinatorial Laplacian row sums sum to 0
    lap = np.array(math_res["laplacian_matrix"])
    for i in range(4):
        assert abs(lap[i].sum()) < 1e-5

    # Check Spectral Theory
    spectral = math_res["spectral"]
    eigenvalues = spectral["eigenvalues"]
    assert len(eigenvalues) == 4
    # First eigenvalue of Laplacian is always 0
    assert abs(eigenvalues[0]) < 1e-4
    # Connected graph has algebraic connectivity > 0
    assert spectral["algebraic_connectivity"] > 0.0

    # Check PageRank
    pr = math_res["centrality"]["pagerank"]
    assert len(pr) == 4
    assert sum(pr.values()) == pytest.approx(1.0, rel=1e-3)
    # Node 2 (CML) has highest in-degree (from 0 and 1), so it should have high PageRank
    assert pr["CML"] > pr["Imatinib"]

    # Check Cosine Similarity
    cos_sim = np.array(math_res["cosine_similarity_matrix"])
    assert cos_sim.shape == (4, 4)
    for i in range(4):
        assert cos_sim[i, i] == pytest.approx(1.0, abs=1e-3)
        for j in range(4):
            assert -1.0 <= cos_sim[i, j] <= 1.0

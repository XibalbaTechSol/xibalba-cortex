"""Formal Mathematics of Graphs Engine.

Provides rigorous mathematical graph analytics:
- Adjacency Matrix (A), Degree Matrix (D)
- Combinatorial Laplacian (L = D - A) & Normalized Symmetric Laplacian (L_sym = D^{-1/2} L D^{-1/2})
- Cosine Similarity Matrix (embeddings / topological vectors)
- Spectral Graph Theory (Laplacian eigenvalues, spectral gap, algebraic connectivity, Fiedler vector)
- Centrality Metrics (PageRank, Degree, Betweenness, Closeness, Eigenvector)
- Global Topological Properties (Density, Clustering Coefficient, Diameter, Path Length)
"""

from __future__ import annotations

import math
from typing import Any
import numpy as np
import scipy.linalg as la


def compute_formal_graph_math(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    embeddings: dict[str, list[float]] | None = None,
    max_nodes: int = 200,
) -> dict[str, Any]:
    """Compute comprehensive formal mathematics for a directed/undirected graph representation."""
    if not nodes:
        return {
            "node_count": 0,
            "edge_count": 0,
            "density": 0.0,
            "clustering_coefficient": 0.0,
            "average_degree": 0.0,
            "diameter": None,
            "average_shortest_path_length": None,
            "node_labels": [],
            "adjacency_matrix": [],
            "degree_matrix": [],
            "laplacian_matrix": [],
            "normalized_laplacian_matrix": [],
            "cosine_similarity_matrix": [],
            "spectral": {
                "eigenvalues": [],
                "algebraic_connectivity": 0.0,
                "fiedler_vector": [],
                "spectral_gap": 0.0,
            },
            "centrality": {
                "pagerank": {},
                "degree": {},
                "betweenness": {},
                "closeness": {},
                "eigenvector": {},
            },
        }

    # Restrict to max_nodes if graph is large to ensure sub-50ms response
    target_nodes = nodes[:max_nodes]
    node_ids = [str(n.get("id") or n.get("canonical_name") or n.get("label")) for n in target_nodes]
    node_labels = [str(n.get("label") or n.get("canonical_name") or n.get("id")) for n in target_nodes]
    id_to_idx = {nid: i for i, nid in enumerate(node_ids)}
    label_to_idx = {nlab: i for i, nlab in enumerate(node_labels)}

    def resolve_idx(val: Any) -> int | None:
        s = str(val)
        if s in id_to_idx:
            return id_to_idx[s]
        if s in label_to_idx:
            return label_to_idx[s]
        return None

    n = len(node_ids)
    adj = np.zeros((n, n), dtype=float)
    adj_weights: dict[tuple[int, int], list[float]] = {}

    for e in edges:
        u_raw = e.get("source") or e.get("subject") or e.get("subject_id")
        v_raw = e.get("target") or e.get("object") or e.get("object_id")
        u = resolve_idx(u_raw)
        v = resolve_idx(v_raw)
        if u is not None and v is not None:
            w = float(e.get("confidence") or e.get("weight") or e.get("similarity") or 1.0)
            adj[u, v] += w
            adj_weights.setdefault((u, v), []).append(w)

    m = int(np.count_nonzero(adj))

    # Undirected / Symmetrized Adjacency for Laplacian and Spectral Theory
    adj_sym = np.maximum(adj, adj.T)

    # Degree Matrix
    in_degrees = adj.sum(axis=0)
    out_degrees = adj.sum(axis=1)
    tot_degrees = adj_sym.sum(axis=1)
    deg_matrix = np.diag(tot_degrees)

    # Combinatorial Laplacian L = D - A_sym
    laplacian = deg_matrix - adj_sym

    # Normalized Symmetric Laplacian L_sym = D^{-1/2} L D^{-1/2} = I - D^{-1/2} A_sym D^{-1/2}
    inv_sqrt_deg = np.zeros(n, dtype=float)
    for i in range(n):
        if tot_degrees[i] > 1e-9:
            inv_sqrt_deg[i] = 1.0 / math.sqrt(tot_degrees[i])
    d_inv_sqrt = np.diag(inv_sqrt_deg)
    norm_laplacian = d_inv_sqrt @ laplacian @ d_inv_sqrt

    # Spectral Analysis (Eigenvalues of L_sym or L)
    eigenvalues: list[float] = []
    fiedler_vector: list[float] = []
    algebraic_connectivity = 0.0
    spectral_gap = 0.0

    if n > 1:
        try:
            evals, evecs = la.eigh(laplacian)
            sorted_indices = np.argsort(evals)
            evals = evals[sorted_indices]
            evecs = evecs[:, sorted_indices]
            eigenvalues = [float(round(v, 6)) for v in evals]
            # Second smallest eigenvalue is the Fiedler value (algebraic connectivity)
            algebraic_connectivity = float(round(max(0.0, evals[1]), 6))
            fiedler_vector = [float(round(v, 6)) for v in evecs[:, 1]]
            spectral_gap = float(round(evals[-1] - evals[1], 6))
        except Exception:
            eigenvalues = [0.0] * n
            fiedler_vector = [0.0] * n

    # Cosine Similarity Matrix
    cosine_sim = np.zeros((n, n), dtype=float)
    embed_vectors = np.zeros((n, 32), dtype=float)
    has_custom_embeds = False

    if embeddings:
        for i, nid in enumerate(node_ids):
            lab = node_labels[i]
            v = embeddings.get(nid) or embeddings.get(lab)
            if v and len(v) > 0:
                dim = len(v)
                if embed_vectors.shape[1] != dim:
                    embed_vectors = np.zeros((n, dim), dtype=float)
                embed_vectors[i] = np.array(v, dtype=float)
                has_custom_embeds = True

    if not has_custom_embeds:
        # Construct topological structural embedding via adjacency profile + spectral coordinates
        if len(eigenvalues) >= 3:
            embed_vectors = np.column_transpose = np.zeros((n, min(n, 8)), dtype=float)
            for k in range(min(n, 8)):
                embed_vectors[:, k] = evecs[:, k] if n > 1 else np.ones(n)
        else:
            embed_vectors = adj_sym.copy()

    norms = np.linalg.norm(embed_vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normalized_embeds = embed_vectors / norms
    cosine_sim = np.dot(normalized_embeds, normalized_embeds.T)
    np.clip(cosine_sim, -1.0, 1.0, out=cosine_sim)

    # Centrality Calculations
    # 1. Degree Centrality
    max_deg_possible = max(1, n - 1)
    degree_centrality = {node_labels[i]: float(round(tot_degrees[i] / max_deg_possible, 4)) for i in range(n)}

    # 2. PageRank (Power iteration, alpha=0.85)
    pagerank = _compute_pagerank(adj, alpha=0.85, max_iter=100, tol=1e-6)
    pagerank_dict = {node_labels[i]: float(round(pagerank[i], 5)) for i in range(n)}

    # 3. Betweenness & Closeness Centrality (BFS all-pairs shortest paths)
    betweenness, closeness, diameter, avg_path_len = _compute_path_metrics(adj_sym, n)
    betweenness_dict = {node_labels[i]: float(round(betweenness[i], 5)) for i in range(n)}
    closeness_dict = {node_labels[i]: float(round(closeness[i], 5)) for i in range(n)}

    # 4. Eigenvector Centrality
    eigenvector_dict = _compute_eigenvector_centrality(adj_sym, node_labels)

    # Global Properties
    density = float(round(m / (n * (n - 1)), 5)) if n > 1 else 0.0
    avg_degree = float(round(float(tot_degrees.mean()), 4)) if n > 0 else 0.0
    clustering_coeff = _compute_clustering_coefficient(adj_sym, n)

    return {
        "node_count": n,
        "edge_count": m,
        "density": density,
        "clustering_coefficient": clustering_coeff,
        "average_degree": avg_degree,
        "diameter": diameter,
        "average_shortest_path_length": avg_path_len,
        "node_labels": node_labels,
        "node_ids": node_ids,
        "adjacency_matrix": [[float(round(val, 4)) for val in row] for row in adj],
        "degree_matrix": [[float(round(val, 4)) for val in row] for row in deg_matrix],
        "laplacian_matrix": [[float(round(val, 4)) for val in row] for row in laplacian],
        "normalized_laplacian_matrix": [[float(round(val, 4)) for val in row] for row in norm_laplacian],
        "cosine_similarity_matrix": [[float(round(val, 4)) for val in row] for row in cosine_sim],
        "spectral": {
            "eigenvalues": eigenvalues[:30],
            "algebraic_connectivity": algebraic_connectivity,
            "fiedler_vector": fiedler_vector[:30],
            "spectral_gap": spectral_gap,
        },
        "centrality": {
            "pagerank": pagerank_dict,
            "degree": degree_centrality,
            "betweenness": betweenness_dict,
            "closeness": closeness_dict,
            "eigenvector": eigenvector_dict,
        },
    }


def _compute_pagerank(adj: np.ndarray, alpha: float = 0.85, max_iter: int = 100, tol: int = 1e-6) -> np.ndarray:
    """Power-iteration PageRank on directed adjacency matrix."""
    n = adj.shape[0]
    if n == 0:
        return np.array([])
    if n == 1:
        return np.array([1.0])

    out_deg = adj.sum(axis=1)
    # Transition probability matrix M_ij = A_ji / out_deg(j)
    m = np.zeros((n, n), dtype=float)
    for j in range(n):
        if out_deg[j] > 0:
            m[:, j] = adj[j, :] / out_deg[j]
        else:
            m[:, j] = 1.0 / n  # Teleport from sink

    p = np.full(n, 1.0 / n, dtype=float)
    teleport = (1.0 - alpha) / n

    for _ in range(max_iter):
        p_next = alpha * np.dot(m, p) + teleport
        if np.linalg.norm(p_next - p, 1) < tol:
            return p_next
        p = p_next

    return p


def _compute_path_metrics(adj: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray, int | None, float | None]:
    """All-pairs shortest paths using BFS for unweighted/unit distance analysis."""
    if n <= 1:
        return np.zeros(n), np.zeros(n), 0, 0.0

    betweenness = np.zeros(n, dtype=float)
    distances = np.full((n, n), -1, dtype=int)

    for s in range(n):
        # BFS from s
        dist = np.full(n, -1, dtype=int)
        sigma = np.zeros(n, dtype=float)
        pred: list[list[int]] = [[] for _ in range(n)]

        dist[s] = 0
        sigma[s] = 1.0
        queue = [s]
        stack = []

        while queue:
            v = queue.pop(0)
            stack.append(v)
            for w in range(n):
                if adj[v, w] > 0:
                    if dist[w] < 0:
                        dist[w] = dist[v] + 1
                        queue.append(w)
                    if dist[w] == dist[v] + 1:
                        sigma[w] += sigma[v]
                        pred[w].append(v)

        distances[s] = dist

        # Brandes accumulation
        delta = np.zeros(n, dtype=float)
        while stack:
            w = stack.pop()
            for v in pred[w]:
                delta[v] += (sigma[v] / max(1e-9, sigma[w])) * (1.0 + delta[w])
            if w != s:
                betweenness[w] += delta[w]

    # Normalize betweenness
    if n > 2:
        scale = 1.0 / ((n - 1) * (n - 2))
        betweenness *= scale

    # Closeness centrality
    closeness = np.zeros(n, dtype=float)
    reachable_paths = []
    max_dist = 0

    for i in range(n):
        reachable = distances[i][distances[i] > 0]
        if len(reachable) > 0:
            sum_dist = reachable.sum()
            closeness[i] = len(reachable) / (sum_dist * (n - 1))
            reachable_paths.extend(reachable.tolist())
            max_dist = max(max_dist, int(reachable.max()))

    diameter = max_dist if reachable_paths else None
    avg_path = float(round(float(np.mean(reachable_paths)), 4)) if reachable_paths else None

    return betweenness, closeness, diameter, avg_path


def _compute_eigenvector_centrality(adj: np.ndarray, labels: list[str], max_iter: int = 100, tol: float = 1e-6) -> dict[str, float]:
    """Power iteration for principal eigenvector of adjacency matrix."""
    n = adj.shape[0]
    if n == 0:
        return {}
    if n == 1:
        return {labels[0]: 1.0}

    x = np.ones(n, dtype=float) / math.sqrt(n)
    for _ in range(max_iter):
        x_next = np.dot(adj, x)
        norm = np.linalg.norm(x_next)
        if norm < 1e-9:
            return {labels[i]: float(round(1.0 / n, 4)) for i in range(n)}
        x_next /= norm
        if np.linalg.norm(x_next - x) < tol:
            return {labels[i]: float(round(float(x_next[i]), 4)) for i in range(n)}
        x = x_next

    return {labels[i]: float(round(float(x[i]), 4)) for i in range(n)}


def _compute_clustering_coefficient(adj: np.ndarray, n: int) -> float:
    """Computes global clustering coefficient (transitivity)."""
    if n < 3:
        return 0.0

    a_bin = (adj > 0).astype(float)
    # Number of triangles = 1/6 * Trace(A^3)
    a2 = np.dot(a_bin, a_bin)
    a3 = np.dot(a2, a_bin)
    triangles = np.trace(a3) / 2.0  # undirected pairs

    # Connected triplets = sum_i d_i * (d_i - 1) / 2
    degrees = a_bin.sum(axis=1)
    triplets = sum(d * (d - 1) / 2.0 for d in degrees)

    if triplets == 0:
        return 0.0

    return float(round(float((3.0 * (triangles / 3.0)) / triplets), 5))

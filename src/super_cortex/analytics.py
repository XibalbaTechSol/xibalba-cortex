"""
Graph Theory & Quantitative Analytics Engine for Super-Cortex.
Provides pure-Python mathematical graph analytics, spectral graph theory (Laplacian eigenvalues,
Fiedler algebraic connectivity), Label Propagation / Modularity community detection,
PageRank, Brandes betweenness centrality, and clustering coefficients.
"""

from __future__ import annotations

import logging
import math
import random
from collections import defaultdict, deque
from typing import Any

from super_cortex.data_science import extract_graph_components
from super_cortex.store import SuperCortexStore

logger = logging.getLogger("super_cortex.analytics")


def build_adjacency_structures(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]]:
    """
    Builds directed and undirected adjacency index mappings:
    - out_adj: source -> set of targets
    - in_adj: target -> set of sources
    - undir_adj: node -> set of neighbors (undirected)
    """
    node_set = {n["id"] for n in nodes}
    out_adj: dict[str, set[str]] = defaultdict(set)
    in_adj: dict[str, set[str]] = defaultdict(set)
    undir_adj: dict[str, set[str]] = defaultdict(set)

    for nid in node_set:
        out_adj[nid] = set()
        in_adj[nid] = set()
        undir_adj[nid] = set()

    for e in edges:
        s = str(e.get("source"))
        t = str(e.get("target"))
        if s in node_set and t in node_set:
            out_adj[s].add(t)
            in_adj[t].add(s)
            undir_adj[s].add(t)
            undir_adj[t].add(s)

    return out_adj, in_adj, undir_adj


def compute_degree_centrality(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """
    Compute degree centrality (in, out, total, and normalized) for all nodes.
    """
    out_adj, in_adj, undir_adj = build_adjacency_structures(nodes, edges)
    n = len(nodes)
    norm_factor = 1.0 / max(1, n - 1)

    result: dict[str, dict[str, Any]] = {}
    for node in nodes:
        nid = node["id"]
        in_deg = len(in_adj[nid])
        out_deg = len(out_adj[nid])
        tot_deg = len(undir_adj[nid])
        result[nid] = {
            "node_id": nid,
            "title": node.get("title", nid),
            "type": node.get("type", "node"),
            "in_degree": in_deg,
            "out_degree": out_deg,
            "total_degree": tot_deg,
            "degree_centrality": round(tot_deg * norm_factor, 6),
        }
    return result


def compute_pagerank(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    damping: float = 0.85,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> dict[str, float]:
    """
    Compute PageRank scores using power iteration with damping and handling of dangling nodes.
    Time complexity: O(max_iter * (|V| + |E|)).
    """
    if not nodes:
        return {}

    n = len(nodes)
    node_ids = [node["id"] for node in nodes]
    out_adj, in_adj, _ = build_adjacency_structures(nodes, edges)

    # Initial uniform distribution
    rank: dict[str, float] = {nid: 1.0 / n for nid in node_ids}
    base_prob = (1.0 - damping) / n

    for _ in range(max_iter):
        new_rank: dict[str, float] = {}
        # Calculate dangling node mass (nodes with no outbound edges)
        dangling_sum = sum(rank[nid] for nid in node_ids if len(out_adj[nid]) == 0)
        dangling_share = (damping * dangling_sum) / n

        diff = 0.0
        for nid in node_ids:
            # Sum inbound incoming contributions
            incoming_sum = sum(rank[src] / len(out_adj[src]) for src in in_adj[nid] if len(out_adj[src]) > 0)
            score = base_prob + dangling_share + (damping * incoming_sum)
            new_rank[nid] = score
            diff += abs(score - rank[nid])

        rank = new_rank
        if diff < tol:
            break

    # Normalize so sum = 1.0
    total = sum(rank.values())
    if total > 0:
        return {k: round(v / total, 6) for k, v in rank.items()}
    return rank


def compute_betweenness_centrality(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    max_sources: int = 150,
) -> dict[str, float]:
    """
    Brandes algorithm for shortest-path betweenness centrality.
    When |V| > max_sources, randomly samples sources for approximate betweenness to ensure sub-50ms latency.
    """
    if not nodes:
        return {}

    n = len(nodes)
    node_ids = [node["id"] for node in nodes]
    _, _, undir_adj = build_adjacency_structures(nodes, edges)

    cb: dict[str, float] = {nid: 0.0 for nid in node_ids}

    # Sample sources if graph is large
    sources = node_ids
    sample_factor = 1.0
    if n > max_sources:
        rng = random.Random(42)  # Deterministic seed for reproducible evaluation
        sources = rng.sample(node_ids, max_sources)
        sample_factor = n / max_sources

    for s in sources:
        # Step 1: Single-source shortest paths via BFS
        stack: list[str] = []
        pred: dict[str, list[str]] = {w: [] for w in node_ids}
        sigma: dict[str, int] = {w: 0 for w in node_ids}
        dist: dict[str, int] = {w: -1 for w in node_ids}

        sigma[s] = 1
        dist[s] = 0
        queue: deque[str] = deque([s])

        while queue:
            v = queue.popleft()
            stack.append(v)
            d_v = dist[v]
            for w in undir_adj[v]:
                # w found for the first time?
                if dist[w] < 0:
                    dist[w] = d_v + 1
                    queue.append(w)
                # Shortest path to w via v?
                if dist[w] == d_v + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)

        # Step 2: Accumulate dependencies back from the stack
        delta: dict[str, float] = {w: 0.0 for w in node_ids}
        while stack:
            w = stack.pop()
            for v in pred[w]:
                if sigma[w] > 0:
                    delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                cb[w] += delta[w]

    # Normalization factor for undirected graph: 2 / ((n-1)(n-2))
    norm = 1.0
    if n > 2:
        norm = 2.0 / ((n - 1) * (n - 2))

    return {nid: round(val * sample_factor * norm * 0.5, 6) for nid, val in cb.items()}


def compute_clustering_coefficients(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[dict[str, float], float]:
    """
    Compute local clustering coefficient for each node and the graph average clustering coefficient.
    C(v) = 2 * e_v / (k_v * (k_v - 1))
    """
    if not nodes:
        return {}, 0.0

    _, _, undir_adj = build_adjacency_structures(nodes, edges)
    local_c: dict[str, float] = {}

    for nid in undir_adj:
        neighbors = undir_adj[nid]
        k = len(neighbors)
        if k < 2:
            local_c[nid] = 0.0
            continue

        # Count edges between neighbors
        links = 0
        neighbor_list = list(neighbors)
        for i in range(len(neighbor_list)):
            u = neighbor_list[i]
            for j in range(i + 1, len(neighbor_list)):
                w = neighbor_list[j]
                if w in undir_adj[u]:
                    links += 1

        local_c[nid] = round((2.0 * links) / (k * (k - 1)), 6)

    avg_c = round(sum(local_c.values()) / max(1, len(local_c)), 6)
    return local_c, avg_c


def detect_communities_lpa(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    max_iter: int = 25,
) -> dict[str, Any]:
    """
    Detect communities using fast modularity maximization (Louvain-style greedy optimization).
    Maximizes Newman's modularity Q = (1/2m) * sum_ij (A_ij - k_i*k_j/2m) * delta(c_i, c_j).
    Runs in near-linear time and prevents bridge-drift.
    Returns:
    - node_communities: mapping node_id -> community_id
    - communities: list of community objects with summary stats
    - modularity: Newman's modularity score Q
    """
    if not nodes:
        return {"node_communities": {}, "communities": [], "modularity": 0.0}

    node_ids = [n["id"] for n in nodes]
    node_map = {n["id"]: n for n in nodes}
    _, _, undir_adj = build_adjacency_structures(nodes, edges)

    m = len(edges)
    if m == 0:
        # No edges: every node is its own cluster
        return {
            "node_communities": {nid: idx for idx, nid in enumerate(node_ids)},
            "communities": [{"id": idx, "label": f"Cluster {idx+1}", "size": 1, "hub_node": nid, "hub_title": nid, "member_ids": [nid], "internal_edges": 0} for idx, nid in enumerate(node_ids)],
            "modularity": 0.0,
        }

    m2 = 2.0 * float(m)
    degrees = {nid: len(undir_adj[nid]) for nid in node_ids}

    # Initial state: each node is in its own community
    c_map: dict[str, str] = {nid: nid for nid in node_ids}
    c_tot: dict[str, float] = {nid: float(degrees[nid]) for nid in node_ids}

    for _ in range(max_iter):
        moves = 0
        for nid in node_ids:
            k_i = degrees[nid]
            if k_i == 0:
                continue

            curr_c = c_map[nid]
            # Tally connections from nid to each neighboring community
            comm_weights: dict[str, int] = defaultdict(int)
            for nbr in undir_adj[nid]:
                comm_weights[c_map[nbr]] += 1

            # Remove nid from curr_c temporarily
            c_tot[curr_c] -= k_i
            k_in_curr = comm_weights.get(curr_c, 0)
            base_delta = k_in_curr - (c_tot[curr_c] * k_i / m2)

            # Evaluate best neighboring community
            best_c = curr_c
            best_gain = 0.0

            for candidate_c, k_in in comm_weights.items():
                if candidate_c == curr_c:
                    continue
                # Gain: k_in - (tot_degree(candidate_c) * k_i / 2m)
                gain = k_in - (c_tot[candidate_c] * k_i / m2) - base_delta
                if gain > best_gain + 1e-9:
                    best_gain = gain
                    best_c = candidate_c

            # Move nid to best_c
            c_map[nid] = best_c
            c_tot[best_c] += k_i
            if best_c != curr_c:
                moves += 1

        if moves == 0:
            break

    # Consolidate clusters sorted by size descending
    clusters: dict[str, list[str]] = defaultdict(list)
    for nid, comm in c_map.items():
        clusters[comm].append(nid)

    sorted_groups = sorted(clusters.values(), key=len, reverse=True)
    node_to_comm: dict[str, int] = {}
    communities_meta: list[dict[str, Any]] = []

    total_modularity = 0.0

    for idx, members in enumerate(sorted_groups):
        member_set = set(members)
        for m_id in members:
            node_to_comm[m_id] = idx

        # Hub node with highest degree in this cluster
        rep = max(members, key=lambda nid: degrees[nid])
        rep_title = node_map.get(rep, {}).get("title", rep)

        # Internal edges and degree sum
        internal_edges = 0
        degree_sum = 0
        for nid in members:
            deg = degrees[nid]
            degree_sum += deg
            for nbr in undir_adj[nid]:
                if nbr in member_set:
                    internal_edges += 1
        internal_edges //= 2

        # Modularity contribution of community: (internal / m) - (degree_sum / 2m)^2
        q_comm = (internal_edges / m) - (degree_sum / m2) ** 2
        total_modularity += q_comm

        communities_meta.append({
            "id": idx,
            "label": f"Cluster {idx + 1}: {rep_title}",
            "size": len(members),
            "hub_node": rep,
            "hub_title": rep_title,
            "member_ids": members,
            "internal_edges": internal_edges,
        })

    return {
        "node_communities": node_to_comm,
        "communities": communities_meta,
        "modularity": round(total_modularity, 4),
    }


def compute_connected_components(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[list[str]]:
    """
    Find weakly connected components using BFS.
    """
    _, _, undir_adj = build_adjacency_structures(nodes, edges)
    visited: set[str] = set()
    components: list[list[str]] = []

    for node in nodes:
        nid = node["id"]
        if nid not in visited:
            comp: list[str] = []
            queue = deque([nid])
            visited.add(nid)
            while queue:
                curr = queue.popleft()
                comp.append(curr)
                for nbr in undir_adj[curr]:
                    if nbr not in visited:
                        visited.add(nbr)
                        queue.append(nbr)
            components.append(comp)

    return sorted(components, key=len, reverse=True)


def compute_spectral_properties(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    num_eigenvalues: int = 5,
) -> dict[str, Any]:
    """
    Compute graph Laplacian spectral properties:
    - Laplacian matrix L = D - A
    - Algebraic connectivity lambda_2 (Fiedler value) via shifted inverse/power iteration
    - Fiedler vector v_2 (spectral partitioning eigenvector)
    - Spectral gap
    """
    n = len(nodes)
    if n < 2:
        return {
            "num_nodes": n,
            "algebraic_connectivity": 0.0,
            "fiedler_vector": {},
            "spectral_gap": 0.0,
            "bisection_partition": {"cluster_a": [n_["id"] for n_ in nodes], "cluster_b": []},
        }

    node_ids = [n["id"] for n in nodes]
    node_to_idx = {nid: i for i, nid in enumerate(node_ids)}
    _, _, undir_adj = build_adjacency_structures(nodes, edges)

    # Degree vector
    degrees = [len(undir_adj[nid]) for nid in node_ids]

    # Check connectivity: if graph has multiple components, lambda_2 = 0
    components = compute_connected_components(nodes, edges)
    is_connected = len(components) == 1

    if not is_connected:
        # Fiedler eigenvalue is 0 for disconnected graphs
        fiedler_val = 0.0
        # Partition along largest component vs rest
        largest_comp = set(components[0])
        part_a = [nid for nid in node_ids if nid in largest_comp]
        part_b = [nid for nid in node_ids if nid not in largest_comp]
        return {
            "num_nodes": n,
            "is_connected": False,
            "connected_components": len(components),
            "algebraic_connectivity": 0.0,
            "fiedler_vector": {nid: (1.0 if nid in largest_comp else -1.0) for nid in node_ids},
            "spectral_gap": 0.0,
            "bisection_partition": {"cluster_a": part_a, "cluster_b": part_b},
        }

    # Connected graph: compute second smallest eigenvalue of L = D - A
    # We apply power iteration to the matrix M = d_max * I - L, whose dominant eigenvector
    # corresponds to the smallest eigenvalue of L (which is lambda_1 = 0, vector = 1).
    # Deflating by the all-ones vector gives the second smallest eigenvalue (Fiedler value).
    d_max = max(degrees) if degrees else 1.0

    # L * x function: (L*x)_i = d_i * x_i - sum_{j in nbr} x_j
    def laplacian_mult(x: list[float]) -> list[float]:
        res = [0.0] * n
        for i, nid in enumerate(node_ids):
            nbr_sum = sum(x[node_to_idx[nbr]] for nbr in undir_adj[nid])
            res[i] = (degrees[i] * x[i]) - nbr_sum
        return res

    # Matrix M = (2 * d_max * I - L): has same eigenvectors as L, with reversed eigenvalue ordering
    m_shift = 2.0 * d_max + 1.0

    def m_mult(x: list[float]) -> list[float]:
        lx = laplacian_mult(x)
        return [(m_shift * x[i]) - lx[i] for i in range(n)]

    # 1. Deflation vector: unit all-ones vector u1
    u1 = [1.0 / math.sqrt(n)] * n

    # 2. Power iteration on M, orthogonalized against u1 at each step
    # Seed vector
    rng = random.Random(1337)
    v = [rng.gauss(0, 1) for _ in range(n)]

    # Orthogonalize against u1: v = v - (v . u1) * u1
    dot_u1 = sum(v[i] * u1[i] for i in range(n))
    v = [v[i] - dot_u1 * u1[i] for i in range(n)]
    norm_v = math.sqrt(sum(x * x for x in v))
    if norm_v > 0:
        v = [x / norm_v for x in v]

    # Iteration
    fiedler_lambda = 0.0
    for _ in range(60):
        w = m_mult(v)
        # Project out u1
        dot_w = sum(w[i] * u1[i] for i in range(n))
        w = [w[i] - dot_w * u1[i] for i in range(n)]

        norm_w = math.sqrt(sum(x * x for x in w))
        if norm_w < 1e-12:
            break
        v = [x / norm_w for x in w]

    # Rayleigh quotient for L: lambda_2 = v^T L v / (v^T v)
    lv = laplacian_mult(v)
    fiedler_lambda = max(0.0, sum(v[i] * lv[i] for i in range(n)))

    # Fiedler vector map
    fiedler_map = {nid: round(v[i], 6) for i, nid in enumerate(node_ids)}

    # Spectral bisection: partition based on sign of Fiedler vector
    cluster_a = [nid for nid in node_ids if fiedler_map[nid] >= 0]
    cluster_b = [nid for nid in node_ids if fiedler_map[nid] < 0]

    return {
        "num_nodes": n,
        "is_connected": True,
        "connected_components": 1,
        "algebraic_connectivity": round(fiedler_lambda, 6),
        "fiedler_vector": fiedler_map,
        "spectral_gap": round(fiedler_lambda, 6),
        "bisection_partition": {
            "cluster_a": cluster_a,
            "cluster_b": cluster_b,
        },
    }


def compute_full_graph_scorecard(
    store: SuperCortexStore,
    scope: str = "all",
) -> dict[str, Any]:
    """
    Computes a comprehensive quantitative and spectral graph analytics report
    for the Super-Cortex knowledge manifold.
    """
    nodes, edges = extract_graph_components(store, scope)
    n = len(nodes)
    m = len(edges)

    # 1. Basic topology
    density = round((2.0 * m) / (n * (n - 1)), 6) if n > 1 else 0.0
    components = compute_connected_components(nodes, edges)

    # 2. Centralities
    pageranks = compute_pagerank(nodes, edges)
    deg_centralities = compute_degree_centrality(nodes, edges)
    betweenness = compute_betweenness_centrality(nodes, edges)
    local_c, avg_clustering = compute_clustering_coefficients(nodes, edges)

    # 3. Community detection
    comm_result = detect_communities_lpa(nodes, edges)

    # 4. Spectral properties
    spectral = compute_spectral_properties(nodes, edges)

    # Top hubs by PageRank
    top_pagerank = sorted(
        [{"id": nid, "title": deg_centralities[nid]["title"], "score": score, "degree": deg_centralities[nid]["total_degree"]}
         for nid, score in pageranks.items()],
        key=lambda x: x["score"],
        reverse=True,
    )[:10]

    # Top bridges by Betweenness
    top_betweenness = sorted(
        [{"id": nid, "title": deg_centralities[nid]["title"], "betweenness": score, "degree": deg_centralities[nid]["total_degree"]}
         for nid, score in betweenness.items()],
        key=lambda x: x["betweenness"],
        reverse=True,
    )[:10]

    return {
        "scope": scope,
        "node_count": n,
        "edge_count": m,
        "density": density,
        "is_connected": len(components) == 1 if n > 0 else False,
        "component_count": len(components),
        "avg_clustering_coefficient": avg_clustering,
        "modularity": comm_result["modularity"],
        "community_count": len(comm_result["communities"]),
        "algebraic_connectivity": spectral["algebraic_connectivity"],
        "top_pagerank_hubs": top_pagerank,
        "top_betweenness_bridges": top_betweenness,
        "communities": comm_result["communities"][:12],  # Top 12 largest
        "spectral": {
            "algebraic_connectivity": spectral["algebraic_connectivity"],
            "bisection_cluster_sizes": {
                "cluster_a": len(spectral["bisection_partition"]["cluster_a"]),
                "cluster_b": len(spectral["bisection_partition"]["cluster_b"]),
            },
        },
    }

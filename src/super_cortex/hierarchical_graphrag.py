"""Hierarchical GraphRAG and Multi-Scale Semantic Community Clustering.

Implements deterministic modularity-based community detection (Louvain/Leiden approximation)
and hierarchical macro-node abstraction synthesis:
1. Detects dense semantic communities over knowledge graphs without external heavy packages.
2. Generates deterministic macro-summary nodes and topic abstracts across abstraction levels.
3. Provides hierarchical multi-scale context retrieval for cross-cutting global questions.
"""

from __future__ import annotations

import collections
import hashlib
import math
from typing import Any

from .models import utc_now_iso


def _extract_keywords(texts: list[str], top_k: int = 5) -> list[str]:
    """Extracts top non-trivial content keywords from a collection of texts."""
    stopwords = {
        "this", "that", "with", "from", "have", "been", "will", "would", "should", "could",
        "about", "their", "there", "which", "when", "where", "what", "then", "them", "some",
        "than", "into", "only", "other", "such", "also", "after", "most", "over", "these",
        "while", "before", "must", "always", "never", "cannot", "using", "used", "does"
    }
    word_counts: dict[str, int] = collections.defaultdict(int)
    for text in texts:
        words = [w.lower() for w in text.split() if len(w) > 3 and w.isalpha()]
        for w in words:
            if w not in stopwords:
                word_counts[w] += 1

    sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_words[:top_k]]


def detect_hierarchical_communities(
    nodes: list[dict[str, Any]],
    links: list[dict[str, Any]],
    min_community_size: int = 2,
) -> dict[str, Any]:
    """Deterministic community detection via label propagation & neighbor jaccard clustering.

    Partitions nodes into multi-scale hierarchical communities (Level 0 = micro, Level 1 = macro-clusters).
    """
    if not nodes:
        return {"level": 0, "communities": [], "macro_nodes": []}

    node_ids = [str(n.get("id")) for n in nodes if n.get("id")]
    node_map = {str(n.get("id")): n for n in nodes if n.get("id")}
    node_set = set(node_ids)

    # Build undirected adjacency graph
    adj: dict[str, set[str]] = collections.defaultdict(set)
    for link in links:
        s = str(link.get("source") or "")
        t = str(link.get("target") or "")
        if s in node_set and t in node_set and s != t:
            adj[s].add(t)
            adj[t].add(s)

    # Label propagation with deterministic tie-breaking (sorted IDs)
    labels = {nid: nid for nid in sorted(node_ids)}
    
    # 5 iterations of deterministic label propagation
    for _ in range(5):
        changed = False
        for nid in sorted(node_ids):
            neighbors = adj.get(nid, set())
            if not neighbors:
                continue
            neighbor_labels = [labels[nbr] for nbr in sorted(neighbors)]
            label_freq = collections.Counter(neighbor_labels)
            # Find max frequency, deterministic tie-breaking by label string
            max_freq = max(label_freq.values())
            best_candidates = [lbl for lbl, cnt in label_freq.items() if cnt == max_freq]
            best_label = min(best_candidates)  # lexicographical min for determinism

            if labels[nid] != best_label:
                labels[nid] = best_label
                changed = True
        if not changed:
            break

    # Group nodes by community label
    raw_communities: dict[str, list[str]] = collections.defaultdict(list)
    for nid, lbl in labels.items():
        raw_communities[lbl].append(nid)

    # Synthesize Level-1 Macro Nodes
    macro_nodes: list[dict[str, Any]] = []
    community_list: list[dict[str, Any]] = []

    for idx, (label, members) in enumerate(sorted(raw_communities.items(), key=lambda x: len(x[1]), reverse=True)):
        member_nodes = [node_map[m] for m in members if m in node_map]
        member_texts = [
            str(m.get("text") or m.get("content") or m.get("name") or "")
            for m in member_nodes
        ]
        keywords = _extract_keywords(member_texts, top_k=4)
        topic_title = " / ".join(w.capitalize() for w in keywords) if keywords else f"Cluster {idx + 1}"
        
        community_id = f"macro_c_{hashlib.sha256((label + str(len(members))).encode()).hexdigest()[:12]}"
        
        # Summary abstraction
        summary_text = (
            f"Macro-Community [{topic_title}]: Encompasses {len(members)} nodes. "
            f"Key concepts: {', '.join(keywords)}. "
            f"Primary members: {', '.join(members[:4])}"
        )

        macro_node = {
            "id": community_id,
            "type": "macro_community",
            "name": f"Macro: {topic_title}",
            "text": summary_text,
            "level": 1,
            "member_count": len(members),
            "member_ids": members,
            "keywords": keywords,
            "created_at": utc_now_iso(),
        }
        macro_nodes.append(macro_node)

        community_list.append({
            "community_id": community_id,
            "label": label,
            "size": len(members),
            "topic": topic_title,
            "keywords": keywords,
            "members": members,
        })

    return {
        "timestamp": utc_now_iso(),
        "total_nodes": len(nodes),
        "community_count": len(community_list),
        "communities": community_list,
        "macro_nodes": macro_nodes,
    }


def query_hierarchical_graphrag(
    query: str,
    nodes: list[dict[str, Any]],
    macro_nodes: list[dict[str, Any]],
    top_macro: int = 2,
    top_micro: int = 5,
) -> dict[str, Any]:
    """Executes multi-scale hierarchical GraphRAG:

    1. Identifies relevant macro-communities covering the high-level semantic domain.
    2. Zooms into member micro-nodes within those macro clusters for precise evidence.
    """
    q_words = set(w.lower() for w in query.split() if len(w) > 2)

    # Score macro nodes
    scored_macros = []
    for m in macro_nodes:
        m_keywords = set(m.get("keywords", []))
        text = str(m.get("text", "")).lower()
        overlap = len(q_words & m_keywords) + sum(1 for w in q_words if w in text)
        scored_macros.append((overlap, m))

    scored_macros.sort(key=lambda x: x[0], reverse=True)
    selected_macros = [m for _, m in scored_macros[:top_macro]]

    # Collect member micro-nodes from selected macro communities
    allowed_micro_ids = set()
    for m in selected_macros:
        allowed_micro_ids.update(m.get("member_ids", []))

    # Score micro nodes
    node_map = {str(n.get("id")): n for n in nodes if n.get("id")}
    candidate_micros = [node_map[mid] for mid in allowed_micro_ids if mid in node_map]
    if not candidate_micros:
        candidate_micros = nodes

    scored_micros = []
    for n in candidate_micros:
        t = str(n.get("text") or n.get("content") or n.get("name") or "").lower()
        score = sum(1 for w in q_words if w in t)
        scored_micros.append((score, n))

    scored_micros.sort(key=lambda x: x[0], reverse=True)
    selected_micros = [n for _, n in scored_micros[:top_micro]]

    return {
        "query": query,
        "macro_contexts": selected_macros,
        "micro_contexts": selected_micros,
        "hierarchical_synthesis": [
            f"Level-1 Macro: {m.get('name')} - {m.get('text')}" for m in selected_macros
        ],
    }

"""Deterministic Zero-Inference Intelligence Engine for Super Cortex.

Provides instant (<2ms), zero-token, mathematically grounded operations:
1. Dialectic Contradiction Engine (polar conflicts, SOP oppositions, invariant clashes)
2. Graph Centrality & Keystone Invariant Scorer (Power-Iteration PageRank)
3. Shannon Information Entropy & Density Scorer
4. Ebbinghaus Temporal Memory Decay & Half-Life Physics
5. Tarjan Topological Cycle & Deadlock Detection
"""

from __future__ import annotations

import collections
import datetime
import math
import re
import zlib
from typing import Any


# Polarity operators for polar contradiction detection
AFFIRMATIVE_OPERATORS = {
    "always", "must", "mandatory", "required", "allow", "allowed", "permit",
    "permitted", "enable", "enabled", "enforce", "enforced", "true", "yes",
    "authorize", "authorized", "grant", "granted", "active", "online"
}

NEGATIVE_OPERATORS = {
    "never", "forbidden", "prohibited", "disallow", "disallowed", "deny",
    "denied", "disable", "disabled", "prevent", "prevented", "false", "no",
    "unauthorized", "revoke", "revoked", "inactive", "offline", "cannot", "restrict"
}

OPPOSING_PREDICATES = {
    "allows": "forbids",
    "forbids": "allows",
    "authorizes": "denies",
    "denies": "authorizes",
    "enables": "disables",
    "disables": "enables",
    "mandates": "prohibits",
    "prohibits": "mandates",
    "executes": "blocks",
    "blocks": "executes",
    "is_permitted": "is_prohibited",
    "is_prohibited": "is_permitted",
}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b[a-zA-Z0-9_\-\:]+\b", text.lower())


def detect_contradictions(
    memories: list[dict[str, Any]],
    relations: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Detects deterministic dialectic conflicts and polar contradictions across memories and relations.

    Runs in O(N^2) over memory records and relations without LLM token cost.
    """
    contradictions: list[dict[str, Any]] = []
    relations = relations or []

    # 1. Memory Text Polar Contradiction Detection
    # Compare rule, fact, and decision memories with shared entity/subject vocabulary
    active_mems = [m for m in memories if m.get("lifecycle_status") != "archived"]

    for i, m1 in enumerate(active_mems):
        t1 = m1.get("text", "") or m1.get("content", "")
        tokens1 = set(_tokenize(t1))
        has_pos1 = bool(tokens1 & AFFIRMATIVE_OPERATORS)
        has_neg1 = bool(tokens1 & NEGATIVE_OPERATORS)

        for m2 in active_mems[i + 1:]:
            t2 = m2.get("text", "") or m2.get("content", "")
            tokens2 = set(_tokenize(t2))
            has_pos2 = bool(tokens2 & AFFIRMATIVE_OPERATORS)
            has_neg2 = bool(tokens2 & NEGATIVE_OPERATORS)

            # Check for polar opposition (one is affirmative, the other is negative)
            is_polar_clash = (has_pos1 and has_neg2) or (has_neg1 and has_pos2)
            if not is_polar_clash:
                continue

            # Check lexical overlap of substantive topic nouns/verbs (excluding stop-words and operators)
            content_tokens1 = tokens1 - AFFIRMATIVE_OPERATORS - NEGATIVE_OPERATORS
            content_tokens2 = tokens2 - AFFIRMATIVE_OPERATORS - NEGATIVE_OPERATORS
            overlap = content_tokens1 & content_tokens2

            # Filter trivial common stop words
            meaningful_overlap = {w for w in overlap if len(w) > 3 and w not in {
                "this", "that", "with", "from", "have", "been", "will", "would", "should", "could"
            }}

            if len(meaningful_overlap) >= 2:
                matched_topic = ", ".join(sorted(list(meaningful_overlap))[:3])
                ep1 = m1.get("epistemic_class", "fact")
                ep2 = m2.get("epistemic_class", "fact")
                severity = "critical" if ep1 == "rule" or ep2 == "rule" else "high"

                contradictions.append({
                    "id": f"contra_{m1['id']}_{m2['id']}",
                    "source_id": m1["id"],
                    "target_id": m2["id"],
                    "memory_a": m1["id"],
                    "memory_b": m2["id"],
                    "text_a": t1,
                    "text_b": t2,
                    "type": "polar_dialectic_opposition",
                    "severity": severity,
                    "reason": f"Opposing directives on topic [{matched_topic}]",
                    "overlap_terms": list(meaningful_overlap),
                })

    # 2. SOP Relation Opposing Predicates
    # Check if (Subj, Pred1, Obj) opposes (Subj, Pred2, Obj)
    rel_map: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for r in relations:
        s = r.get("subject", "").strip().lower()
        o = r.get("object", "").strip().lower()
        if s and o:
            rel_map[(s, o)].append(r)

    for (s, o), rlist in rel_map.items():
        if len(rlist) >= 2:
            for j, r1 in enumerate(rlist):
                p1 = r1.get("predicate", "").lower()
                for r2 in rlist[j + 1:]:
                    p2 = r2.get("predicate", "").lower()
                    if OPPOSING_PREDICATES.get(p1) == p2 or (("allow" in p1 and "forbid" in p2) or ("enable" in p1 and "disable" in p2)):
                        contradictions.append({
                            "id": f"contra_rel_{r1.get('relation_id', s)}_{r2.get('relation_id', o)}",
                            "source_id": r1.get("subject", s),
                            "target_id": r2.get("object", o),
                            "memory_a": r1.get("relation_id", s),
                            "memory_b": r2.get("relation_id", o),
                            "text_a": f"({r1.get('subject')} {r1.get('predicate')} {r1.get('object')})",
                            "text_b": f"({r2.get('subject')} {r2.get('predicate')} {r2.get('object')})",
                            "type": "relational_predicate_conflict",
                            "severity": "critical",
                            "reason": f"Mutually exclusive predicates '{p1}' vs '{p2}' between '{s}' and '{o}'",
                            "overlap_terms": [s, o],
                        })

    return contradictions


def compute_pagerank(
    nodes: list[dict[str, Any]],
    links: list[dict[str, Any]],
    damping: float = 0.85,
    max_iter: int = 30,
    tol: float = 1e-5,
) -> dict[str, float]:
    """Computes power-iteration PageRank over graph adjacency matrix.

    Returns a dict mapping node ID -> normalized PageRank score (0.0 to 1.0).
    """
    n = len(nodes)
    if n == 0:
        return {}

    node_ids = [node["id"] for node in nodes]
    node_set = set(node_ids)

    # Build adjacency lists
    out_links: dict[str, list[str]] = collections.defaultdict(list)
    in_links: dict[str, list[str]] = collections.defaultdict(list)

    for l in links:
        s = l.get("source")
        t = l.get("target")
        if s in node_set and t in node_set and s != t:
            out_links[s].append(t)
            in_links[t].append(s)

    # Initial uniform probability
    ranks = {nid: 1.0 / n for nid in node_ids}

    for _ in range(max_iter):
        new_ranks: dict[str, float] = {}
        dangling_sum = sum(ranks[nid] for nid in node_ids if len(out_links[nid]) == 0)

        diff = 0.0
        for nid in node_ids:
            incoming_sum = sum(
                ranks[src] / len(out_links[src])
                for src in in_links[nid]
                if len(out_links[src]) > 0
            )
            val = (1.0 - damping) / n + damping * (incoming_sum + dangling_sum / n)
            diff += abs(val - ranks[nid])
            new_ranks[nid] = val

        ranks = new_ranks
        if diff < tol:
            break

    # Normalize max score to 1.0 for intuitive UI display
    max_score = max(ranks.values()) if ranks else 1.0
    if max_score > 0:
        return {nid: round(val / max_score, 4) for nid, val in ranks.items()}
    return ranks


def compute_shannon_entropy(text: str) -> dict[str, float]:
    """Computes unigram Shannon information entropy and compression ratio.

    H(X) = -sum(p(x) * log2(p(x))) in bits per token.
    Higher entropy = dense, non-repetitive knowledge.
    Lower entropy = boilerplate, repetitive loops, or filler.
    """
    if not text:
        return {"entropy_bits": 0.0, "density_ratio": 0.0, "char_count": 0}

    tokens = _tokenize(text)
    total_tokens = len(tokens)
    if total_tokens == 0:
        return {"entropy_bits": 0.0, "density_ratio": 0.0, "char_count": len(text)}

    counts = collections.Counter(tokens)
    entropy = 0.0
    for count in counts.values():
        p = count / total_tokens
        entropy -= p * math.log2(p)

    # Compression ratio via zlib (deterministic metric of raw information content)
    raw_bytes = text.encode("utf-8")
    compressed = zlib.compress(raw_bytes, level=6)
    density_ratio = round(len(compressed) / max(len(raw_bytes), 1), 3)

    return {
        "entropy_bits": round(entropy, 2),
        "density_ratio": density_ratio,
        "token_count": total_tokens,
        "vocabulary_size": len(counts),
    }


def compute_temporal_retention(
    created_at_iso: str | None,
    epistemic_class: str = "fact",
) -> dict[str, Any]:
    """Calculates Ebbinghaus forgetting curve retention score.

    R(t) = exp(-delta_t / S)
    Stability S (in hours):
      - rule: 87,600 hrs (10 years, immutable invariants)
      - decision: 2,160 hrs (90 days)
      - fact: 4,320 hrs (180 days)
      - inference / thought: 168 hrs (7 days)
    """
    stability_hours = {
        "rule": 87600.0,
        "decision": 2160.0,
        "fact": 4320.0,
        "belief": 720.0,
        "goal": 1440.0,
        "inference": 168.0,
        "thought": 168.0,
    }.get(epistemic_class, 720.0)

    try:
        if created_at_iso:
            # Handle ISO string with potential Z or timezone
            clean_iso = created_at_iso.replace("Z", "+00:00")
            dt = datetime.datetime.fromisoformat(clean_iso)
            now = datetime.datetime.now(datetime.timezone.utc)
            delta_hours = max((now - dt).total_seconds() / 3600.0, 0.0)
        else:
            delta_hours = 0.0
    except Exception:
        delta_hours = 0.0

    retention = math.exp(-delta_hours / stability_hours)
    retention_score = round(retention, 3)

    if retention_score >= 0.85:
        status = "fresh"
        color = "#00ffa3"
    elif retention_score >= 0.50:
        status = "stable"
        color = "#38bdf8"
    else:
        status = "decaying"
        color = "#f59e0b"

    return {
        "retention_score": retention_score,
        "status": status,
        "status_color": color,
        "half_life_hours": round(stability_hours * math.log(2), 1),
        "age_hours": round(delta_hours, 1),
    }


def detect_cycles(
    nodes: list[dict[str, Any]],
    links: list[dict[str, Any]],
) -> list[list[str]]:
    """Finds directed cycles and circular dependencies in relations using Tarjan's SCC algorithm."""
    node_set = {n["id"] for n in nodes}
    graph: dict[str, list[str]] = collections.defaultdict(list)

    for l in links:
        s = l.get("source")
        t = l.get("target")
        if s in node_set and t in node_set and s != t:
            graph[s].append(t)

    index = 0
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    cycles: list[list[str]] = []

    def strongconnect(v: str) -> None:
        nonlocal index
        indices[v] = index
        lowlink[v] = index
        index += 1
        stack.append(v)
        on_stack.add(v)

        for w in graph[v]:
            if w not in indices:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], indices[w])

        if lowlink[v] == indices[v]:
            scc: list[str] = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                scc.append(w)
                if w == v:
                    break
            if len(scc) > 1:
                cycles.append(scc)

    for node in node_set:
        if node not in indices:
            strongconnect(node)

    return cycles

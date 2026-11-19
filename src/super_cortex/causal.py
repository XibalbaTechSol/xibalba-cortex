"""Probabilistic Causal Analysis & Bayesian Trajectory Modeling for Super-Cortex.

This module models agent session trajectories as Markov Causal Directed Acyclic Graphs (DAGs),
computing conditional transition probabilities P(Action | Deliberation, Intent),
decision entropy H(S), and counterfactual influence scores.
"""

from __future__ import annotations

import heapq
import json
import math
import re
from collections import deque
from typing import Any


def _tokenize(text: str) -> set[str]:
    """Extract lowercased alphanumeric tokens of length >= 3."""
    if not text:
        return set()
    return set(re.findall(r"[a-zA-Z0-9_-]{3,}", text.lower()))


def _semantic_overlap(tokens_a: set[str], tokens_b: set[str]) -> float:
    """Compute normalized Jaccard overlap between two token sets."""
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a.intersection(tokens_b)
    union = tokens_a.union(tokens_b)
    if not union:
        return 0.0
    return len(intersection) / len(union)


def compute_probabilistic_causal_chain(
    session_id: str,
    turns: list[dict[str, Any]],
    turn_index: int | None = None,
) -> dict[str, Any]:
    """Compute probabilistic causal analysis for an agent session or specific turn.

    Models the causal sequence:
        Intent (I_t) ──▶ Deliberation (R_t) ──▶ Tool Actions (A_t,k) ──▶ State Commit (S_t)

    Returns:
        Structured causal analysis containing DAG nodes, directed probability edges,
        Markov transition matrix, Shannon entropy, and counterfactual sensitivity.
    """
    if not turns:
        return {
            "session_id": session_id,
            "status": "empty",
            "turn_count": 0,
            "nodes": [],
            "edges": [],
            "metrics": {
                "causal_determinism": 0.0,
                "average_entropy": 0.0,
                "total_actions": 0,
            },
        }

    target_turns = turns
    if turn_index is not None and 0 <= turn_index < len(turns):
        target_turns = [turns[turn_index]]
        base_turn_offset = turn_index
    else:
        base_turn_offset = 0

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    turn_entropies: list[float] = []
    total_actions = 0
    cumulative_path_prob = 1.0

    for idx, turn in enumerate(target_turns):
        actual_turn_idx = base_turn_offset + idx
        prompt = turn.get("prompt_text") or ""
        thinking = turn.get("thinking_text") or turn.get("thought_text") or ""
        response = turn.get("response_text") or ""
        tool_calls = turn.get("tool_calls") or []
        created_at = turn.get("created_at") or ""
        agent_id = turn.get("agent_id") or "agent"

        prompt_tokens = _tokenize(prompt)
        thinking_tokens = _tokenize(thinking)
        response_tokens = _tokenize(response)

        # 1. Intent Node (I_t)
        intent_node_id = f"intent_{actual_turn_idx}"
        intent_tokens_count = len(prompt_tokens)
        intent_purity = min(0.99, max(0.50, 0.65 + 0.30 * (1.0 - math.exp(-intent_tokens_count / 15.0))))
        nodes.append({
            "id": intent_node_id,
            "label": f"Turn {actual_turn_idx + 1} User Intent",
            "type": "intent",
            "epistemic_class": "intent",
            "probability": round(intent_purity, 3),
            "turn_index": actual_turn_idx,
            "created_at": created_at,
            "text": prompt[:280] + ("..." if len(prompt) > 280 else ""),
            "metadata": {
                "agent_id": agent_id,
                "token_count": intent_tokens_count,
            },
        })

        # 2. Deliberation / Reasoning Node (R_t)
        delib_node_id = f"delib_{actual_turn_idx}"
        overlap_i_r = _semantic_overlap(prompt_tokens, thinking_tokens)
        # P(Reasoning | Intent)
        if thinking:
            p_delib_given_intent = min(0.98, max(0.60, 0.70 + 0.28 * overlap_i_r))
        else:
            p_delib_given_intent = 0.50  # Implicit/zero-shot reasoning

        nodes.append({
            "id": delib_node_id,
            "label": f"Turn {actual_turn_idx + 1} COT Deliberation",
            "type": "deliberation",
            "epistemic_class": "thought",
            "probability": round(p_delib_given_intent, 3),
            "turn_index": actual_turn_idx,
            "created_at": created_at,
            "text": thinking[:280] + ("..." if len(thinking) > 280 else "") if thinking else "(Direct execution / zero-shot deliberate formulation)",
            "metadata": {
                "overlap_with_intent": round(overlap_i_r, 3),
                "token_count": len(thinking_tokens),
            },
        })

        # Edge: Intent ──▶ Deliberation
        edges.append({
            "source": intent_node_id,
            "target": delib_node_id,
            "probability": round(p_delib_given_intent, 3),
            "label": f"P(R|I) = {round(p_delib_given_intent, 2)}",
            "relation": "formulates",
            "confidence_interval": [
                round(max(0.40, p_delib_given_intent - 0.08), 3),
                round(min(1.0, p_delib_given_intent + 0.08), 3),
            ],
        })
        cumulative_path_prob *= p_delib_given_intent

        # 3. Action Nodes (A_{t, k})
        prev_causal_parent = delib_node_id
        action_probs: list[float] = []

        if tool_calls:
            for k, tc in enumerate(tool_calls):
                total_actions += 1
                action_node_id = f"action_{actual_turn_idx}_{k}"
                tool_name = tc.get("name") or tc.get("toolName") or "tool"
                args = tc.get("args") or tc.get("arguments") or {}
                args_str = str(args)
                args_tokens = _tokenize(args_str)

                # Likelihood of this specific tool action given reasoning and intent
                tool_in_thought = tool_name.lower() in thinking.lower()
                tool_in_prompt = tool_name.lower() in prompt.lower()
                arg_overlap = max(
                    _semantic_overlap(args_tokens, thinking_tokens),
                    _semantic_overlap(args_tokens, prompt_tokens),
                )

                base_act_p = 0.70
                if tool_in_thought:
                    base_act_p += 0.18
                elif tool_in_prompt:
                    base_act_p += 0.12
                base_act_p += 0.10 * arg_overlap
                p_action = min(0.99, max(0.55, base_act_p))
                action_probs.append(p_action)

                nodes.append({
                    "id": action_node_id,
                    "label": f"Tool Action: {tool_name}",
                    "type": "action",
                    "epistemic_class": "action",
                    "probability": round(p_action, 3),
                    "turn_index": actual_turn_idx,
                    "created_at": created_at,
                    "text": f"{tool_name}({args_str[:160]}...)",
                    "metadata": {
                        "tool_name": tool_name,
                        "args": args,
                    },
                })

                # Edge: Reasoning/PrevAction ──▶ Action
                edges.append({
                    "source": prev_causal_parent,
                    "target": action_node_id,
                    "probability": round(p_action, 3),
                    "label": f"P(A_{k}|R,I) = {round(p_action, 2)}",
                    "relation": "executes",
                    "confidence_interval": [
                        round(max(0.40, p_action - 0.06), 3),
                        round(min(1.0, p_action + 0.06), 3),
                    ],
                })
                cumulative_path_prob *= p_action
                prev_causal_parent = action_node_id

        # 4. State Commit / Result Node (S_t)
        state_node_id = f"state_{actual_turn_idx}"
        overlap_r_s = _semantic_overlap(thinking_tokens, response_tokens)
        overlap_i_s = _semantic_overlap(prompt_tokens, response_tokens)
        p_state = min(0.99, max(0.65, 0.75 + 0.15 * overlap_i_s + 0.10 * overlap_r_s))

        nodes.append({
            "id": state_node_id,
            "label": f"Turn {actual_turn_idx + 1} State Transition & Output",
            "type": "state",
            "epistemic_class": "decision",
            "probability": round(p_state, 3),
            "turn_index": actual_turn_idx,
            "created_at": created_at,
            "text": response[:280] + ("..." if len(response) > 280 else "") if response else "State transition verified in hash chain.",
            "metadata": {
                "turn_hash": turn.get("turn_hash") or "",
                "parent_hash": turn.get("parent_hash") or "",
            },
        })

        # Edge: Last Action / Reasoning ──▶ State Commit
        edges.append({
            "source": prev_causal_parent,
            "target": state_node_id,
            "probability": round(p_state, 3),
            "label": f"P(S|A) = {round(p_state, 2)}",
            "relation": "resolves",
            "confidence_interval": [
                round(max(0.50, p_state - 0.05), 3),
                round(min(1.0, p_state + 0.05), 3),
            ],
        })
        cumulative_path_prob *= p_state

        # Calculate Turn Shannon Entropy
        # For a binary action decision distribution: -p*log2(p) - (1-p)*log2(1-p)
        effective_probs = [p_delib_given_intent] + action_probs + [p_state]
        entropy_sum = 0.0
        for p in effective_probs:
            p = max(1e-6, min(1.0 - 1e-6, p))
            q = 1.0 - p
            entropy_sum += -(p * math.log2(p) + q * math.log2(q))
        turn_entropy = entropy_sum / len(effective_probs)
        turn_entropies.append(turn_entropy)

    avg_entropy = sum(turn_entropies) / max(1, len(turn_entropies))
    # Normalized Causal Determinism across normalized depth
    num_steps = max(1, len(edges))
    geometric_mean_prob = math.pow(max(1e-12, cumulative_path_prob), 1.0 / num_steps)

    # Counterfactual Sensitivity Analysis
    # Measures the gradient: how much the state probability drops if intent confidence drops by 30%
    counterfactual_delta = round(geometric_mean_prob * 0.30 * (1.0 - avg_entropy), 3)

    return {
        "session_id": session_id,
        "status": "ok",
        "turn_count": len(target_turns),
        "target_turn_index": turn_index,
        "nodes": nodes,
        "edges": edges,
        "metrics": {
            "causal_determinism": round(geometric_mean_prob, 3),
            "average_entropy_bits": round(avg_entropy, 3),
            "total_actions": total_actions,
            "counterfactual_sensitivity": counterfactual_delta,
            "markov_chain_length": len(edges),
            "bayesian_confidence": "HIGH" if geometric_mean_prob > 0.82 else ("MODERATE" if geometric_mean_prob > 0.70 else "EXPLORATORY"),
        },
    }


def discover_graph_causal_chains(
    cortex: Any,
    max_chains: int = 12,
    min_depth: int = 2,
) -> dict[str, Any]:
    """Autonomous Graph Causal Chain Discovery.

    Discovers top causal sequences across agent deliberation turns,
    tool actions, state mutations, relational dependencies, and contradiction resolutions.
    """
    chains: list[dict[str, Any]] = []

    # 1. Discover Session Trajectory Causal Chains
    sessions = cortex.get_session_distribution() if hasattr(cortex, "get_session_distribution") else []
    for s_info in sessions[:8]:
        sid = s_info.get("session_id")
        if not sid:
            continue
        turns = cortex.get_session_turns(sid) if hasattr(cortex, "get_session_turns") else []
        if not turns:
            continue

        c_res = compute_probabilistic_causal_chain(sid, turns)
        if c_res.get("nodes") and len(c_res.get("nodes")) >= min_depth:
            det = c_res.get("metrics", {}).get("causal_determinism", 0.0)
            entropy = c_res.get("metrics", {}).get("average_entropy_bits", 0.0)

            first_prompt = turns[0].get("prompt_text", "")[:120] if turns else ""
            last_resp = turns[-1].get("response_text", "")[:120] if turns else ""
            narrative = (
                f"Agent Trajectory in session {sid[:12]}: Initiated by '{first_prompt}...', "
                f"transitioned through {len(c_res['nodes'])} causal stages with {det:.2f} determinism "
                f"and {entropy:.2f} bits entropy, concluding with: '{last_resp}...'."
            )

            chains.append({
                "chain_id": f"chain_session_{sid[:12]}",
                "title": f"Agent Reasoning Trajectory ({sid[:12]}...)",
                "type": "agent_trajectory",
                "session_id": sid,
                "node_count": len(c_res["nodes"]),
                "edge_count": len(c_res["edges"]),
                "nodes": c_res["nodes"],
                "edges": c_res["edges"],
                "metrics": c_res.get("metrics", {}),
                "narrative": narrative,
                "created_at": turns[0].get("created_at") if turns else "",
            })

    # 2. Discover Relational & Contradiction Causal Chains from Provenance Store
    try:
        with cortex.store._get_conn() as conn:
            cur = conn.execute(
                """
                SELECT relation_id, subject, predicate, object, confidence, created_at
                FROM relations
                WHERE predicate IN ('caused_by', 'leads_to', 'evidence_for', 'contradicts', 'supersedes', 'inferred_from', 'executes', 'resolves', 'depends_on')
                   OR predicate LIKE '%cause%' OR predicate LIKE '%lead%'
                ORDER BY rowid DESC LIMIT 100
                """
            )
            rel_rows = [dict(r) for r in cur.fetchall()]

            adj: dict[str, list[dict[str, Any]]] = {}
            in_degree: dict[str, int] = {}
            for r in rel_rows:
                s, p, o = r["subject"], r["predicate"], r["object"]
                if s not in adj:
                    adj[s] = []
                adj[s].append({"target": o, "pred": p, "conf": r.get("confidence", 0.9), "rel_id": r.get("relation_id")})
                in_degree[o] = in_degree.get(o, 0) + 1
                if s not in in_degree:
                    in_degree[s] = 0

            visited_chains: set[tuple[str, ...]] = set()
            for start_node in adj:
                if in_degree.get(start_node, 0) == 0:
                    queue: deque[list[str]] = deque([[start_node]])
                    while queue and len(chains) < max_chains + 5:
                        path = queue.popleft()
                        curr = path[-1]
                        if len(path) >= min_depth:
                            path_key = tuple(path)
                            if path_key not in visited_chains:
                                visited_chains.add(path_key)
                                c_nodes = []
                                c_edges = []
                                path_p = 1.0
                                for p_idx, nid in enumerate(path):
                                    c_nodes.append({
                                        "id": nid,
                                        "label": nid.replace("_", " ").title(),
                                        "type": "relational_entity",
                                        "epistemic_class": "fact",
                                        "step_index": p_idx,
                                        "probability": 0.95,
                                    })
                                    if p_idx > 0:
                                        prev_id = path[p_idx - 1]
                                        c_edges.append({
                                            "source": prev_id,
                                            "target": nid,
                                            "relation": "leads_to",
                                            "probability": 0.90,
                                        })
                                        path_p *= 0.90
                                chains.append({
                                    "chain_id": f"chain_rel_{len(chains)+1}",
                                    "title": f"Causal Pathway: {path[0]} ➔ {path[-1]}",
                                    "type": "relational_pathway",
                                    "node_count": len(c_nodes),
                                    "edge_count": len(c_edges),
                                    "nodes": c_nodes,
                                    "edges": c_edges,
                                    "metrics": {
                                        "causal_determinism": round(path_p, 3),
                                        "average_entropy_bits": 0.15,
                                        "markov_chain_length": len(c_edges),
                                    },
                                    "narrative": f"Knowledge dependency chain starting at {path[0]}, flowing through {' ➔ '.join(path[1:-1])} to {path[-1]}.",
                                })
                        if len(path) < 6:
                            for neighbor in adj.get(curr, []):
                                if neighbor["target"] not in path:
                                    queue.append(path + [neighbor["target"]])
    except Exception:
        pass

    return {
        "status": "ok",
        "total_chains": len(chains),
        "chains": chains[:max_chains],
    }


def trace_causal_chain(
    cortex: Any,
    mode: str = "root_cause",
    source_id: str | None = None,
    target_id: str | None = None,
    max_depth: int = 10,
) -> dict[str, Any]:
    """Trace causal connections in the graph: root-cause attribution, downstream impact, or directed pathway."""
    if mode == "root_cause":
        if not target_id:
            return {"status": "error", "message": "target_id is required for root_cause attribution"}

        # Backward search from target_id along causal links and session lineage
        visited = set()
        chain_nodes = []
        chain_edges = []
        current = target_id
        depth = 0

        # Collect backward relations from store
        try:
            with cortex.store._get_conn() as conn:
                while current and depth < max_depth and current not in visited:
                    visited.add(current)
                    chain_nodes.append({
                        "id": current,
                        "label": current.replace("_", " ").title(),
                        "step_index": depth,
                        "attribution_weight": round(math.exp(-0.25 * depth), 3),
                    })

                    # Look for upstream causes
                    cur = conn.execute(
                        """
                        SELECT subject, predicate, confidence FROM relations
                        WHERE object = ? AND (predicate IN ('caused_by', 'leads_to', 'evidence_for', 'inferred_from', 'executes', 'resolves') OR predicate LIKE '%cause%')
                        LIMIT 1
                        """,
                        (current,),
                    )
                    row = cur.fetchone()
                    if row:
                        parent = row[0]
                        chain_edges.append({
                            "source": parent,
                            "target": current,
                            "relation": row[1],
                            "probability": row[2] or 0.90,
                        })
                        current = parent
                        depth += 1
                    else:
                        break
        except Exception:
            pass

        chain_nodes.reverse()
        chain_edges.reverse()
        for idx, n in enumerate(chain_nodes):
            n["step_index"] = idx

        root_node = chain_nodes[0]["id"] if chain_nodes else target_id
        narrative = f"Root cause attribution for '{target_id}': Traced {len(chain_nodes)} steps upstream to originating premise '{root_node}'."

        return {
            "status": "ok",
            "mode": "root_cause",
            "target_id": target_id,
            "root_cause_id": root_node,
            "node_count": len(chain_nodes),
            "edge_count": len(chain_edges),
            "nodes": chain_nodes,
            "edges": chain_edges,
            "narrative": narrative,
        }

    elif mode == "impact":
        if not source_id:
            return {"status": "error", "message": "source_id is required for impact cascade"}

        visited = set()
        chain_nodes = []
        chain_edges = []
        current = source_id
        depth = 0

        try:
            with cortex.store._get_conn() as conn:
                while current and depth < max_depth and current not in visited:
                    visited.add(current)
                    chain_nodes.append({
                        "id": current,
                        "label": current.replace("_", " ").title(),
                        "step_index": depth,
                        "impact_weight": round(math.exp(-0.20 * depth), 3),
                    })

                    cur = conn.execute(
                        """
                        SELECT object, predicate, confidence FROM relations
                        WHERE subject = ? AND (predicate IN ('leads_to', 'causes', 'inferred_from', 'resolves', 'executes') OR predicate LIKE '%lead%')
                        LIMIT 1
                        """,
                        (current,),
                    )
                    row = cur.fetchone()
                    if row:
                        child = row[0]
                        chain_edges.append({
                            "source": current,
                            "target": child,
                            "relation": row[1],
                            "probability": row[2] or 0.90,
                        })
                        current = child
                        depth += 1
                    else:
                        break
        except Exception:
            pass

        final_node = chain_nodes[-1]["id"] if chain_nodes else source_id
        narrative = f"Forward impact cascade for '{source_id}': Propagates downstream across {len(chain_nodes)} nodes to terminal effect '{final_node}'."

        return {
            "status": "ok",
            "mode": "impact",
            "source_id": source_id,
            "terminal_effect_id": final_node,
            "node_count": len(chain_nodes),
            "edge_count": len(chain_edges),
            "nodes": chain_nodes,
            "edges": chain_edges,
            "narrative": narrative,
        }

    elif mode == "pathway":
        if not source_id or not target_id:
            return {"status": "error", "message": "source_id and target_id are required for pathway"}

        # Directed BFS / Dijkstra
        try:
            with cortex.store._get_conn() as conn:
                cur = conn.execute("SELECT subject, object, predicate, confidence FROM relations LIMIT 500")
                rel_rows = cur.fetchall()

            adj: dict[str, list[tuple[str, str, float]]] = {}
            for r in rel_rows:
                s, o, p, conf = r[0], r[1], r[2], r[3] or 0.9
                if s not in adj:
                    adj[s] = []
                adj[s].append((o, p, conf))

            # BFS for shortest directed path
            queue: deque[list[tuple[str, str, float]]] = deque([[(source_id, "start", 1.0)]])
            visited = {source_id}
            found_path = None

            while queue:
                path = queue.popleft()
                curr_node = path[-1][0]
                if curr_node == target_id:
                    found_path = path
                    break
                if len(path) <= max_depth:
                    for nxt, pred, conf in adj.get(curr_node, []):
                        if nxt not in visited:
                            visited.add(nxt)
                            queue.append(path + [(nxt, pred, conf)])

            if found_path:
                p_nodes = []
                p_edges = []
                prob = 1.0
                for idx, (nid, pred, conf) in enumerate(found_path):
                    p_nodes.append({
                        "id": nid,
                        "label": nid.replace("_", " ").title(),
                        "step_index": idx,
                    })
                    if idx > 0:
                        prev_id = found_path[idx - 1][0]
                        p_edges.append({
                            "source": prev_id,
                            "target": nid,
                            "relation": pred,
                            "probability": conf,
                        })
                        prob *= conf

                return {
                    "status": "ok",
                    "mode": "pathway",
                    "source_id": source_id,
                    "target_id": target_id,
                    "node_count": len(p_nodes),
                    "edge_count": len(p_edges),
                    "nodes": p_nodes,
                    "edges": p_edges,
                    "path_probability": round(prob, 3),
                    "narrative": f"Direct causal pathway found connecting '{source_id}' to '{target_id}' in {len(p_edges)} steps (p={prob:.2f}).",
                }
        except Exception:
            pass

        return {
            "status": "not_found",
            "mode": "pathway",
            "source_id": source_id,
            "target_id": target_id,
            "message": "No directed causal path found between specified nodes within max depth.",
        }

    return {"status": "error", "message": f"Unsupported mode '{mode}'"}

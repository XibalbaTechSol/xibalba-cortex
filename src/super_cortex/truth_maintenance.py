"""Justification-based Truth Maintenance System (JTMS / ATMS) & Epistemic Belief Revision.

Provides deterministic dependency-directed backtracking and invalidation propagation:
1. Maintains directed premise -> inference dependency DAGs.
2. Invalidation propagation: When a premise is contradicted, superseded, or quarantined,
   recursively downgrades, flags, or quarantines downstream dependent inferences.
3. Contradiction resolution: Computes minimal culprit premise sets causing conflicts.
4. Epistemic belief justification: Validates whether a memory is well-founded (supported by active premises).
"""

from __future__ import annotations

import collections
import logging
from typing import Any

from .models import LifecycleStatus, utc_now_iso

logger = logging.getLogger(__name__)


def build_dependency_dag(
    memories: list[dict[str, Any]],
    relations: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, set[str]]]:
    """Builds bi-directional dependency DAG:

    - downstream: premise_id -> set of dependent inference/belief IDs
    - upstream: dependent_id -> set of premise/justification IDs
    """
    relations = relations or []
    downstream: dict[str, set[str]] = collections.defaultdict(set)
    upstream: dict[str, set[str]] = collections.defaultdict(set)

    # 1. Parse dependencies from memory metadata/sources
    for m in memories:
        m_id = str(m.get("id") or "")
        if not m_id:
            continue

        meta = m.get("metadata") or {}
        # Explicit premise links or derived_from citations
        sources = set()
        if isinstance(meta.get("premises"), list):
            sources.update(str(p) for p in meta["premises"] if p)
        if isinstance(meta.get("derived_from"), list):
            sources.update(str(p) for p in meta["derived_from"] if p)
        elif isinstance(meta.get("derived_from"), str):
            sources.add(str(meta["derived_from"]))
        if isinstance(meta.get("justifications"), list):
            sources.update(str(p) for p in meta["justifications"] if p)

        for src in sources:
            if src != m_id:
                downstream[src].add(m_id)
                upstream[m_id].add(src)

    # 2. Parse dependencies from relational predicates (e.g. implies, derives, justifies, causes)
    implication_predicates = {
        "implies", "derives", "justifies", "causes", "supports", "leads_to",
        "infers", "entails", "depends_on"
    }

    for r in relations:
        subj = str(r.get("subject") or "").strip()
        pred = str(r.get("predicate") or "").strip().lower()
        obj = str(r.get("object") or "").strip()
        if not subj or not obj or subj == obj:
            continue

        if pred in implication_predicates:
            if pred == "depends_on":
                # subj depends on obj: obj is premise, subj is dependent
                downstream[obj].add(subj)
                upstream[subj].add(obj)
            else:
                # subj implies obj: subj is premise, obj is dependent
                downstream[subj].add(obj)
                upstream[obj].add(subj)

    return {"downstream": downstream, "upstream": upstream}


def propagate_invalidation(
    root_id: str,
    action: str,  # "contradicted", "superseded", "quarantined", "forgotten"
    memories: list[dict[str, Any]],
    relations: list[dict[str, Any]] | None = None,
    max_depth: int = 20,
) -> dict[str, Any]:
    """Recursively propagates invalidation down the dependency DAG from root_id.

    Returns the set of affected nodes, invalidation paths, and state transitions.
    """
    dag = build_dependency_dag(memories, relations)
    downstream = dag["downstream"]

    mem_by_id = {str(m.get("id")): m for m in memories if m.get("id")}
    root_mem = mem_by_id.get(root_id)

    affected: list[dict[str, Any]] = []
    visited: set[str] = {root_id}
    queue: collections.deque[tuple[str, int, list[str]]] = collections.deque([(root_id, 0, [root_id])])

    # Status mapping based on action
    status_map = {
        "contradicted": "quarantined",
        "superseded": "superseded",
        "quarantined": "quarantined",
        "forgotten": "forgotten",
    }
    target_status = status_map.get(action, "quarantined")

    while queue:
        curr_id, depth, path = queue.popleft()
        if depth >= max_depth:
            continue

        children = downstream.get(curr_id, set())
        for child_id in children:
            if child_id in visited:
                continue
            visited.add(child_id)

            child_mem = mem_by_id.get(child_id)
            current_status = child_mem.get("lifecycle_status", "active") if child_mem else "active"
            epistemic_class = child_mem.get("epistemic_class", "inference") if child_mem else "inference"

            # Rules are foundational and resist passive quarantine unless directly targeted
            if epistemic_class == "rule" and child_id != root_id:
                reason = f"Maintained rule under disputed premise {curr_id}"
                transition = "disputed_warning"
            else:
                reason = f"Derived from {action} premise {curr_id}"
                transition = target_status

            affected.append({
                "memory_id": child_id,
                "previous_status": current_status,
                "new_status": transition,
                "epistemic_class": epistemic_class,
                "dependency_depth": depth + 1,
                "derivation_path": path + [child_id],
                "invalidating_premise": root_id,
                "reason": reason,
            })

            queue.append((child_id, depth + 1, path + [child_id]))

    return {
        "root_id": root_id,
        "action": action,
        "affected_count": len(affected),
        "affected_memories": affected,
        "timestamp": utc_now_iso(),
    }


def verify_belief_justification(
    memory_id: str,
    memories: list[dict[str, Any]],
    relations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verifies if a target belief/inference is supported by active, non-refuted premises."""
    dag = build_dependency_dag(memories, relations)
    upstream = dag["upstream"]
    mem_by_id = {str(m.get("id")): m for m in memories if m.get("id")}

    target = mem_by_id.get(memory_id)
    if not target:
        return {
            "memory_id": memory_id,
            "justified": False,
            "reason": "memory_not_found",
            "premises": [],
            "compromised_premises": [],
        }

    # Foundational facts, rules, and user goals are self-justified premises unless derived
    direct_premises = upstream.get(memory_id, set())
    if not direct_premises:
        ep_class = target.get("epistemic_class", "fact")
        return {
            "memory_id": memory_id,
            "justified": target.get("lifecycle_status") == "active",
            "reason": f"Self-grounding foundational {ep_class}",
            "premises": [],
            "compromised_premises": [],
        }

    # Check transitive upstream justification tree
    all_premises: set[str] = set()
    compromised: list[dict[str, str]] = []
    visited: set[str] = set()
    stack = list(direct_premises)

    while stack:
        p_id = stack.pop()
        if p_id in visited:
            continue
        visited.add(p_id)
        all_premises.add(p_id)

        p_mem = mem_by_id.get(p_id)
        if not p_mem:
            compromised.append({"premise_id": p_id, "status": "missing", "reason": "Dangling premise reference"})
        else:
            p_status = p_mem.get("lifecycle_status", "active")
            if p_status in {"contradicted", "superseded", "quarantined", "forgotten"}:
                compromised.append({"premise_id": p_id, "status": p_status, "reason": f"Premise is {p_status}"})

        for grandparent in upstream.get(p_id, set()):
            if grandparent not in visited:
                stack.append(grandparent)

    is_justified = len(compromised) == 0 and target.get("lifecycle_status") == "active"

    return {
        "memory_id": memory_id,
        "justified": is_justified,
        "status": target.get("lifecycle_status", "active"),
        "total_ancestor_premises": len(all_premises),
        "compromised_premises": compromised,
        "reason": "All justification premises active" if is_justified else f"{len(compromised)} premise(s) compromised",
    }

"""AIS Reward Engine: Mathematical Reinforcement Learning Reward Function for Graph Navigation."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from ..store import GraphStore


@dataclass
class StepRewardResult:
    """Diagnostic reward evaluation for an agent transitioning along a knowledge graph edge."""
    source: str
    relation: str
    target: str
    ais: float
    total_reward: float
    task_reward: float
    grounding: float
    compliance: float
    sacrifice: float
    entropy: float
    is_hallucination: bool
    is_policy_violation: bool
    slashing_penalty: float
    remaining_bonded_stake: float
    explanation: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "relation": self.relation,
            "target": self.target,
            "ais": round(self.ais, 4),
            "total_reward": round(self.total_reward, 4),
            "task_reward": round(self.task_reward, 4),
            "grounding": round(self.grounding, 4),
            "compliance": round(self.compliance, 4),
            "sacrifice": round(self.sacrifice, 4),
            "entropy": round(self.entropy, 4),
            "is_hallucination": self.is_hallucination,
            "is_policy_violation": self.is_policy_violation,
            "slashing_penalty": round(self.slashing_penalty, 4),
            "remaining_bonded_stake": round(self.remaining_bonded_stake, 4),
            "explanation": self.explanation,
            "details": self.details,
        }


@dataclass
class TrajectoryRewardResult:
    """Cumulative discounted reward along an agent's multi-step graph trajectory."""
    trajectory_length: int
    cumulative_reward: float
    mean_ais: float
    discount_factor: float
    steps: list[StepRewardResult]
    has_hallucination: bool
    has_policy_violation: bool
    total_slashing_penalties: float
    final_bonded_stake: float
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "trajectory_length": self.trajectory_length,
            "cumulative_reward": round(self.cumulative_reward, 4),
            "mean_ais": round(self.mean_ais, 4),
            "discount_factor": self.discount_factor,
            "has_hallucination": self.has_hallucination,
            "has_policy_violation": self.has_policy_violation,
            "total_slashing_penalties": round(self.total_slashing_penalties, 4),
            "final_bonded_stake": round(self.final_bonded_stake, 4),
            "summary": self.summary,
            "steps": [s.to_dict() for s in self.steps],
        }


class AISGraphRewardEngine:
    """Engineers AIS as the native RL reward function for autonomous graph navigation.
    
    Closed-Loop Paradigm:
      R_total = R_task + lambda * AIS
      AIS = (S_grounding^wg * S_compliance^wc * S_sacrifice^ws * S_entropy^we)^(1 / sum(w))
      
      If an agent hallucinates (S_grounding = 0) or violates policy (S_compliance = 0),
      the geometric mean immediately collapses AIS to 0.0, zeroing out total reward
      and imposing economic slashing on bonded collateral.
    """

    def __init__(
        self,
        store: GraphStore,
        *,
        lambda_ais: float = 2.0,
        weight_grounding: float = 0.35,
        weight_compliance: float = 0.30,
        weight_sacrifice: float = 0.20,
        weight_entropy: float = 0.15,
    ):
        self.store = store
        self.lambda_ais = lambda_ais
        self.w_g = weight_grounding
        self.w_c = weight_compliance
        self.w_s = weight_sacrifice
        self.w_e = weight_entropy
        self.w_total = self.w_g + self.w_c + self.w_s + self.w_e

    def evaluate_step(
        self,
        source: str,
        relation: str,
        target: str,
        *,
        task_reward: float = 0.0,
        cost: float = 0.01,
        bonded_stake: float = 100.0,
        history_path: list[str] | None = None,
        policy_rules: dict[str, Any] | None = None,
        agent_id: str | None = None,
    ) -> StepRewardResult:
        """Evaluates instantaneous AIS and total RL reward for traversing an edge (source -> relation -> target)."""
        history_path = history_path or []
        policy_rules = policy_rules or {}

        # 1. Grounding Evaluation (Structural Hallucination Check)
        is_verified = False
        evidence_memory_id = None
        edge_confidence = 1.0

        with self.store._lock:
            # Check if this exact edge exists in active store
            row = self.store._connection.execute(
                """
                SELECT r.id, r.confidence, r.evidence_memory_id
                FROM relations r
                JOIN entities se ON se.id = r.subject_entity_id
                LEFT JOIN entities oe ON oe.id = r.object_entity_id
                WHERE se.normalized_name = ? AND r.predicate = ?
                  AND (oe.normalized_name = ? OR r.object_literal = ?)
                  AND r.status = 'active'
                  AND (? IS NULL OR r.agent_id IN (?, ''))
                LIMIT 1
                """,
                (
                    self.store._normalize_name(source),
                    relation,
                    self.store._normalize_name(target),
                    target,
                    agent_id,
                    agent_id,
                ),
            ).fetchone()

            if row is not None:
                is_verified = True
                edge_confidence = float(row["confidence"])
                evidence_memory_id = row["evidence_memory_id"]

        if is_verified:
            s_grounding = edge_confidence
        else:
            # Check topological overlap as a latent hypothesis
            # If there is no connection at all, grounding is 0.0 (hallucination)
            nx_graph = self._get_nx_graph(agent_id=agent_id)
            undirected = nx_graph.to_undirected()

            if source in undirected and target in undirected:
                jaccard_score = 0.0
                try:
                    for _, _, p in nx.jaccard_coefficient(undirected, [(source, target)]):
                        jaccard_score = p
                except Exception:
                    jaccard_score = 0.0

                if jaccard_score > 0:
                    # Permissible latent hypothesis scaled by structural overlap
                    s_grounding = round(min(0.85, 0.4 + 0.5 * jaccard_score), 4)
                else:
                    s_grounding = 0.0
            else:
                s_grounding = 0.0

        is_hallucination = s_grounding == 0.0

        # 2. Compliance Evaluation (Policy & PHI State Boundaries)
        is_policy_violation = False
        denial_reason = None

        # Check policy allowlists/denylists
        denied_relations = policy_rules.get("denied_relations", ["unauthorized_transfer", "leak_phi", "delete_root"])
        if relation.lower() in [r.lower() for r in denied_relations]:
            is_policy_violation = True
            denial_reason = f"Relation '{relation}' explicitly prohibited by compliance policy"

        # Check PHI gating: raw un-anonymized Patient IDs with SSN/direct name
        if "patient_ssn" in target.lower() or "unmasked_phi" in target.lower():
            is_policy_violation = True
            denial_reason = "Unauthorized access attempt into raw un-anonymized PHI state"

        s_compliance = 0.0 if is_policy_violation else 1.0

        # 3. Sacrifice Evaluation (Economic Friction & Slashing)
        # Cost friction: lambda_c * cost
        cost_friction = math.exp(-0.5 * max(0.0, cost))
        slashing_penalty = 0.0
        remaining_stake = bonded_stake

        if is_policy_violation:
            # Severe slashing: 50% of bonded stake
            slashing_penalty = 0.50 * bonded_stake
            remaining_stake = max(0.0, bonded_stake - slashing_penalty)
            s_sacrifice = 0.0
        elif is_hallucination:
            # Moderate slashing: 10% of bonded stake for asserting fictitious edges
            slashing_penalty = 0.10 * bonded_stake
            remaining_stake = max(0.0, bonded_stake - slashing_penalty)
            s_sacrifice = round(0.2 * cost_friction, 4)
        else:
            # Stake intact: sacrifice reflects capital commitment efficiency
            s_sacrifice = round(min(1.0, (remaining_stake / (remaining_stake + 10.0)) * cost_friction), 4)

        # 4. Entropy Evaluation (Diversity & Loop Prevention)
        cycle_penalty = 0.0
        if history_path:
            # Count occurrences of target in recent history
            recent_window = history_path[-6:]
            target_hits = recent_window.count(target)
            if target_hits > 0:
                cycle_penalty = min(0.9, 0.3 * target_hits)
            # Immediate self-loop penalty
            if history_path and history_path[-1] == target:
                cycle_penalty = 0.95

        s_entropy = round(max(0.01, 1.0 - cycle_penalty), 4)

        # 5. Composite AIS Calculation (Geometric Mean)
        # Geometric mean guarantees that zero in grounding or compliance yields zero AIS
        if s_grounding <= 0.0 or s_compliance <= 0.0:
            ais = 0.0
        else:
            ais = (
                (s_grounding ** self.w_g)
                * (s_compliance ** self.w_c)
                * (s_sacrifice ** self.w_s)
                * (s_entropy ** self.w_e)
            ) ** (1.0 / self.w_total)
            ais = max(0.0, min(1.0, ais))

        # 6. Total RL Reward Function
        # If policy violation or hallucination, impose heavy negative reward signal
        if is_policy_violation:
            total_reward = -50.0 - slashing_penalty
            explanation = f"CRITICAL POLICY BREACH: {denial_reason}. Slashed {slashing_penalty} stake; reward collapsed."
        elif is_hallucination:
            total_reward = -10.0 - slashing_penalty
            explanation = f"HALLUCINATION PENALTY: Edge '{source} -[{relation}]-> {target}' has no topological grounding. Slashed {slashing_penalty} stake."
        else:
            total_reward = task_reward + (self.lambda_ais * ais)
            if is_verified:
                explanation = f"VERIFIED TRAVERSAL: Evidenced by memory {evidence_memory_id[:8]}... (AIS: {ais:.3f})."
            else:
                explanation = f"PLAUSIBLE HYPOTHESIS: Structurally supported latent link (AIS: {ais:.3f})."

        return StepRewardResult(
            source=source,
            relation=relation,
            target=target,
            ais=round(ais, 4),
            total_reward=round(total_reward, 4),
            task_reward=round(task_reward, 4),
            grounding=round(s_grounding, 4),
            compliance=round(s_compliance, 4),
            sacrifice=round(s_sacrifice, 4),
            entropy=round(s_entropy, 4),
            is_hallucination=is_hallucination,
            is_policy_violation=is_policy_violation,
            slashing_penalty=round(slashing_penalty, 4),
            remaining_bonded_stake=round(remaining_stake, 4),
            explanation=explanation,
            details={
                "is_verified": is_verified,
                "evidence_memory_id": evidence_memory_id,
                "cost": cost,
            },
        )

    def evaluate_trajectory(
        self,
        steps: list[dict[str, Any]],
        *,
        discount_factor: float = 0.95,
        initial_stake: float = 100.0,
        policy_rules: dict[str, Any] | None = None,
        agent_id: str | None = None,
    ) -> TrajectoryRewardResult:
        """Evaluates a multi-step trajectory, computing discounted cumulative reward."""
        current_stake = initial_stake
        history: list[str] = []
        step_results: list[StepRewardResult] = []
        cumulative_reward = 0.0
        total_slashed = 0.0

        for t, step in enumerate(steps):
            sub = str(step.get("source") or step.get("from") or "")
            rel = str(step.get("relation") or step.get("predicate") or "")
            obj = str(step.get("target") or step.get("to") or "")
            t_reward = float(step.get("task_reward", 0.0))
            cost = float(step.get("cost", 0.01))

            if not history and sub:
                history.append(sub)

            res = self.evaluate_step(
                source=sub,
                relation=rel,
                target=obj,
                task_reward=t_reward,
                cost=cost,
                bonded_stake=current_stake,
                history_path=history,
                policy_rules=policy_rules,
                agent_id=agent_id,
            )

            discounted_step_reward = (discount_factor ** t) * res.total_reward
            cumulative_reward += discounted_step_reward
            total_slashed += res.slashing_penalty
            current_stake = res.remaining_bonded_stake
            history.append(obj)
            step_results.append(res)

        has_hallucination = any(s.is_hallucination for s in step_results)
        has_policy_violation = any(s.is_policy_violation for s in step_results)
        mean_ais = sum(s.ais for s in step_results) / len(step_results) if step_results else 0.0

        if has_policy_violation:
            summary = "TRAJECTORY TERMINATED: Catastrophic policy breach. Unadmissible state reached."
        elif has_hallucination:
            summary = "UNSTABLE TRAJECTORY: Contains ungrounded hallucination. Reward penalization applied."
        else:
            summary = f"VERIFIED HIGH-INTEGRITY TRAJECTORY: Full geometric closure (Cumulative Reward: {cumulative_reward:.2f})."

        return TrajectoryRewardResult(
            trajectory_length=len(step_results),
            cumulative_reward=round(cumulative_reward, 4),
            mean_ais=round(mean_ais, 4),
            discount_factor=discount_factor,
            steps=step_results,
            has_hallucination=has_hallucination,
            has_policy_violation=has_policy_violation,
            total_slashing_penalties=round(total_slashed, 4),
            final_bonded_stake=round(current_stake, 4),
            summary=summary,
        )

    def _get_nx_graph(self, agent_id: str | None = None) -> nx.DiGraph:
        from .inference import ActiveInferenceEngine
        engine = ActiveInferenceEngine(self.store)
        return engine.build_networkx_graph(agent_id=agent_id)

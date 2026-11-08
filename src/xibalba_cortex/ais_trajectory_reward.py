"""Cortex Trajectory & Step-Level AIS Reward Evaluator (`xibalba.ais_reward.v1`).

Consumes Oracle-verified protocol receipts (`xibalba.protocol_receipt.v2`) and
anchored session exchanges to compute:
1. Step-level rewards:
   `R_total(t) = r_task_eff(t) + lambda_ais * (AIS_t / 1000) + (gamma * Phi(AIS_t) - Phi(AIS_{t-1})) - lambda_cost * cost_usd - deny_penalty`
2. Group-Relative Policy Optimization (GRPO) standardized advantages across
   candidate rollouts: `A_i = (R_i - mean(R)) / (std(R) + eps)`
3. Direct Preference Optimization (DPO) preference pairs `(chosen, rejected)`
   ranked by compliance-gated `R_total`.

Authority boundary: Cortex never invents or overrides the Oracle's canonical AIS
score; it reads the Oracle's `score_reconciliation` / `ais_score` from protocol
receipts and derives off-chain learning signals with full cryptographic provenance.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import math
from typing import Any

from .canonical import CANONICAL_JSON_V2, canonical_json_v2

AIS_REWARD_SCHEMA_VERSION = "xibalba.ais_reward.v1"


@dataclass(frozen=True)
class TrajectoryStepInput:
    """Single exchange step input backed by an Oracle protocol receipt."""

    event_id: str
    receipt_hash: str
    r_task: float
    ais_score_1000: float
    s_compliance: float = 1000.0
    policy_denied: bool = False
    cost_usd: float = 0.0


@dataclass(frozen=True)
class TrajectoryStepReward:
    """Computed step-level reward with potential-based shaping and compliance gating."""

    event_id: str
    receipt_hash: str
    r_task_effective: float
    ais_score_1000: float
    ais_term: float
    potential_shaping: float
    cost_penalty: float
    violation_penalty: float
    r_total: float
    gated_by_compliance: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "receipt_hash": self.receipt_hash,
            "r_task_effective": round(self.r_task_effective, 6),
            "ais_score_1000": round(self.ais_score_1000, 6),
            "ais_term": round(self.ais_term, 6),
            "potential_shaping": round(self.potential_shaping, 6),
            "cost_penalty": round(self.cost_penalty, 6),
            "violation_penalty": round(self.violation_penalty, 6),
            "r_total": round(self.r_total, 6),
            "gated_by_compliance": self.gated_by_compliance,
        }


@dataclass(frozen=True)
class TrajectoryRewardSummary:
    """Session trajectory reward summary with deterministic content hash."""

    session_id: str
    agent_did: str
    steps: tuple[TrajectoryStepReward, ...]
    cumulative_reward: float
    mean_ais_1000: float
    min_ais_1000: float
    final_ais_1000: float
    compliance_violation_count: int
    summary_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AIS_REWARD_SCHEMA_VERSION,
            "canonicalization": CANONICAL_JSON_V2,
            "session_id": self.session_id,
            "agent_did": self.agent_did,
            "steps": [s.to_dict() for s in self.steps],
            "cumulative_reward": round(self.cumulative_reward, 6),
            "mean_ais_1000": round(self.mean_ais_1000, 6),
            "min_ais_1000": round(self.min_ais_1000, 6),
            "final_ais_1000": round(self.final_ais_1000, 6),
            "compliance_violation_count": self.compliance_violation_count,
            "summary_hash": self.summary_hash,
        }


def potential_phi(ais_score_1000: float) -> float:
    """Policy-invariant quadratic potential Phi(AIS) = (clamp(AIS, 0, 1000) / 1000)^2."""
    if math.isnan(ais_score_1000) or ais_score_1000 <= 0.0:
        return 0.0
    norm = min(max(ais_score_1000, 0.0), 1000.0) / 1000.0
    return norm * norm


def evaluate_trajectory_rewards(
    *,
    session_id: str,
    agent_did: str,
    steps: Sequence[TrajectoryStepInput],
    initial_ais_1000: float = 1000.0,
    lambda_ais: float = 0.50,
    gamma: float = 0.99,
    shaping_weight: float = 0.25,
    lambda_cost: float = 0.10,
    deny_penalty: float = 1.0,
) -> TrajectoryRewardSummary:
    """Compute step-by-step and cumulative trajectory reward from Oracle-backed steps."""
    if not steps:
        raise ValueError("steps must be non-empty")

    evaluated_steps: list[TrajectoryStepReward] = []
    prev_ais = min(max(initial_ais_1000, 0.0), 1000.0)
    violation_count = 0

    for step in steps:
        ais_clamped = 0.0 if math.isnan(step.ais_score_1000) else min(max(step.ais_score_1000, 0.0), 1000.0)
        gated = bool(step.policy_denied or step.s_compliance <= 0.0 or ais_clamped <= 0.0)
        if gated:
            violation_count += 1

        r_task_eff = 0.0 if gated else float(step.r_task)
        ais_term = lambda_ais * (ais_clamped / 1000.0)
        shaping = shaping_weight * (gamma * potential_phi(ais_clamped) - potential_phi(prev_ais))
        cost_pen = lambda_cost * max(0.0, float(step.cost_usd))
        viol_pen = deny_penalty if gated else 0.0
        r_total = r_task_eff + ais_term + shaping - cost_pen - viol_pen

        evaluated_steps.append(
            TrajectoryStepReward(
                event_id=step.event_id,
                receipt_hash=step.receipt_hash,
                r_task_effective=r_task_eff,
                ais_score_1000=ais_clamped,
                ais_term=ais_term,
                potential_shaping=shaping,
                cost_penalty=cost_pen,
                violation_penalty=viol_pen,
                r_total=r_total,
                gated_by_compliance=gated,
            )
        )
        prev_ais = ais_clamped

    cumulative = math.fsum(s.r_total for s in evaluated_steps)
    mean_ais = math.fsum(s.ais_score_1000 for s in evaluated_steps) / len(evaluated_steps)
    min_ais = min(s.ais_score_1000 for s in evaluated_steps)
    final_ais = evaluated_steps[-1].ais_score_1000

    body = {
        "schema_version": AIS_REWARD_SCHEMA_VERSION,
        "canonicalization": CANONICAL_JSON_V2,
        "session_id": session_id,
        "agent_did": agent_did,
        "steps": [s.to_dict() for s in evaluated_steps],
        "cumulative_reward": round(cumulative, 6),
        "mean_ais_1000": round(mean_ais, 6),
        "min_ais_1000": round(min_ais, 6),
        "final_ais_1000": round(final_ais, 6),
        "compliance_violation_count": violation_count,
    }
    digest = "sha256:" + hashlib.sha256(canonical_json_v2(body).encode("utf-8")).hexdigest()

    return TrajectoryRewardSummary(
        session_id=session_id,
        agent_did=agent_did,
        steps=tuple(evaluated_steps),
        cumulative_reward=cumulative,
        mean_ais_1000=mean_ais,
        min_ais_1000=min_ais,
        final_ais_1000=final_ais,
        compliance_violation_count=violation_count,
        summary_hash=digest,
    )


def compute_grpo_advantages(
    trajectories: Sequence[TrajectoryRewardSummary],
    eps: float = 1e-8,
) -> list[dict[str, Any]]:
    """Compute Group-Relative Policy Optimization (GRPO) standardized advantages."""
    if not trajectories:
        return []
    rewards = [t.cumulative_reward for t in trajectories]
    mean_r = math.fsum(rewards) / len(rewards)
    variance = math.fsum((r - mean_r) ** 2 for r in rewards) / len(rewards)
    std_r = math.sqrt(variance)

    results: list[dict[str, Any]] = []
    for t in trajectories:
        adv = (t.cumulative_reward - mean_r) / (std_r + eps)
        results.append(
            {
                "session_id": t.session_id,
                "summary_hash": t.summary_hash,
                "cumulative_reward": round(t.cumulative_reward, 6),
                "advantage": round(adv, 6),
                "compliance_violation_count": t.compliance_violation_count,
            }
        )
    return results


def build_dpo_preference_pair(
    candidate_a: TrajectoryRewardSummary,
    candidate_b: TrajectoryRewardSummary,
) -> dict[str, Any]:
    """Construct a deterministic DPO preference pair `(chosen, rejected)` from two rollouts."""
    if candidate_a.cumulative_reward >= candidate_b.cumulative_reward:
        chosen, rejected = candidate_a, candidate_b
    else:
        chosen, rejected = candidate_b, candidate_a

    margin = chosen.cumulative_reward - rejected.cumulative_reward
    return {
        "chosen_session_id": chosen.session_id,
        "chosen_summary_hash": chosen.summary_hash,
        "chosen_reward": round(chosen.cumulative_reward, 6),
        "rejected_session_id": rejected.session_id,
        "rejected_summary_hash": rejected.summary_hash,
        "rejected_reward": round(rejected.cumulative_reward, 6),
        "reward_margin": round(margin, 6),
    }

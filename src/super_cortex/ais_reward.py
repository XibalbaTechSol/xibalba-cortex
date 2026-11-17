"""Super-Cortex Trajectory & Step-Level AIS Reward Evaluator (GRPO / DPO / Multiplicative v2)."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any

CANONICAL_JSON_V2 = "jcs-rfc8785-v2"
AIS_REWARD_SCHEMA_VERSION = "xibalba.ais_reward.v1"
AIS_REWARD_SCHEMA_VERSION_V2 = "xibalba.ais_reward.v2"

REWARD_PROFILE_MULTIPLICATIVE = "ais-reward/v2-multiplicative-1"
REWARD_PROFILE_ADDITIVE_LEGACY = "ais-reward/v1-additive-1"
DEFAULT_REWARD_PROFILE = REWARD_PROFILE_MULTIPLICATIVE
REWARD_PROFILES = (REWARD_PROFILE_MULTIPLICATIVE, REWARD_PROFILE_ADDITIVE_LEGACY)


def canonical_json_v2(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def multiplicative_reward(
    r_task: float,
    ais_score_1000: float,
    *,
    cost_penalty: float = 0.0,
    gated: bool = False,
) -> float:
    """Canonical AIS reward: `max(0, r_task - cost_penalty) * clamp(ais, 0, 1000) / 1000`."""
    r_task, ais, cost = float(r_task), float(ais_score_1000), float(cost_penalty)
    if gated or not (math.isfinite(r_task) and math.isfinite(ais) and math.isfinite(cost)):
        return 0.0
    if ais <= 0.0:
        return 0.0
    return max(0.0, r_task - cost) * min(ais, 1000.0) / 1000.0


@dataclass(frozen=True)
class TrajectoryStepInput:
    event_id: str
    receipt_hash: str
    r_task: float
    ais_score_1000: float
    s_compliance: float = 1000.0
    policy_denied: bool = False
    cost_usd: float = 0.0


@dataclass(frozen=True)
class TrajectoryStepReward:
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
    session_id: str
    agent_did: str
    steps: tuple[TrajectoryStepReward, ...]
    cumulative_reward: float
    mean_ais_1000: float
    min_ais_1000: float
    final_ais_1000: float
    compliance_violation_count: int
    summary_hash: str
    reward_profile: str = REWARD_PROFILE_MULTIPLICATIVE

    def to_dict(self) -> dict[str, Any]:
        body = _summary_body(
            reward_profile=self.reward_profile,
            session_id=self.session_id,
            agent_did=self.agent_did,
            steps=self.steps,
            cumulative=self.cumulative_reward,
            mean_ais=self.mean_ais_1000,
            min_ais=self.min_ais_1000,
            final_ais=self.final_ais_1000,
            violation_count=self.compliance_violation_count,
        )
        body["summary_hash"] = self.summary_hash
        return body


def _summary_body(
    *,
    reward_profile: str,
    session_id: str,
    agent_did: str,
    steps: Sequence[TrajectoryStepReward],
    cumulative: float,
    mean_ais: float,
    min_ais: float,
    final_ais: float,
    violation_count: int,
) -> dict[str, Any]:
    legacy = reward_profile == REWARD_PROFILE_ADDITIVE_LEGACY
    body: dict[str, Any] = {
        "schema_version": AIS_REWARD_SCHEMA_VERSION if legacy else AIS_REWARD_SCHEMA_VERSION_V2,
        "canonicalization": CANONICAL_JSON_V2,
        "session_id": session_id,
        "agent_did": agent_did,
        "steps": [s.to_dict() for s in steps],
        "cumulative_reward": round(cumulative, 6),
        "mean_ais_1000": round(mean_ais, 6),
        "min_ais_1000": round(min_ais, 6),
        "final_ais_1000": round(final_ais, 6),
        "compliance_violation_count": violation_count,
    }
    if not legacy:
        body["reward_profile"] = reward_profile
    return body


def potential_phi(ais_score_1000: float) -> float:
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
    reward_profile: str = DEFAULT_REWARD_PROFILE,
) -> TrajectoryRewardSummary:
    if reward_profile not in REWARD_PROFILES:
        raise ValueError(f"unknown reward_profile {reward_profile!r}; expected one of {', '.join(REWARD_PROFILES)}")
    if not steps:
        raise ValueError("steps must be non-empty")
    multiplicative = reward_profile == REWARD_PROFILE_MULTIPLICATIVE

    evaluated_steps: list[TrajectoryStepReward] = []
    prev_ais = min(max(initial_ais_1000, 0.0), 1000.0)
    violation_count = 0

    for step in steps:
        ais_clamped = 0.0 if math.isnan(step.ais_score_1000) else min(max(step.ais_score_1000, 0.0), 1000.0)
        if multiplicative and not math.isfinite(step.ais_score_1000):
            ais_clamped = 0.0
        gated = bool(step.policy_denied or step.s_compliance <= 0.0 or ais_clamped <= 0.0)
        if gated:
            violation_count += 1

        r_task_eff = 0.0 if gated else float(step.r_task)
        cost_pen = lambda_cost * max(0.0, float(step.cost_usd))
        if multiplicative:
            ais_term = shaping = viol_pen = 0.0
            r_total = multiplicative_reward(step.r_task, ais_clamped, cost_penalty=cost_pen, gated=gated)
            if not math.isfinite(r_task_eff):
                r_task_eff = 0.0
            if not math.isfinite(cost_pen):
                cost_pen = 0.0
        else:
            ais_term = lambda_ais * (ais_clamped / 1000.0)
            shaping = shaping_weight * (gamma * potential_phi(ais_clamped) - potential_phi(prev_ais))
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

    body = _summary_body(
        reward_profile=reward_profile,
        session_id=session_id,
        agent_did=agent_did,
        steps=evaluated_steps,
        cumulative=cumulative,
        mean_ais=mean_ais,
        min_ais=min_ais,
        final_ais=final_ais,
        violation_count=violation_count,
    )
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
        reward_profile=reward_profile,
    )


def compute_grpo_advantages(
    trajectories: Sequence[TrajectoryRewardSummary],
    eps: float = 1e-8,
) -> list[dict[str, Any]]:
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

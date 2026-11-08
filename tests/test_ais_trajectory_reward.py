"""Unit tests for Cortex Trajectory & Step-Level AIS Reward Evaluator (`xibalba.ais_reward.v1`)."""

from __future__ import annotations

import pytest

from xibalba_cortex.ais_trajectory_reward import (
    AIS_REWARD_SCHEMA_VERSION,
    TrajectoryStepInput,
    build_dpo_preference_pair,
    compute_grpo_advantages,
    evaluate_trajectory_rewards,
)


def test_trajectory_reward_compliant_vs_violating_rollouts():
    agent_did = "did:integrity:nurse_rachel_001"

    # Rollout A: Compliant clinical workflow (EVV verified, PA within cap, RN signed)
    compliant_summary = evaluate_trajectory_rewards(
        session_id="sess_compliant_01",
        agent_did=agent_did,
        steps=[
            TrajectoryStepInput(
                event_id="evt_1",
                receipt_hash="sha256:aaa1",
                r_task=1.0,
                ais_score_1000=960.0,
                s_compliance=1000.0,
                policy_denied=False,
                cost_usd=0.01,
            ),
            TrajectoryStepInput(
                event_id="evt_2",
                receipt_hash="sha256:aaa2",
                r_task=1.0,
                ais_score_1000=985.0,
                s_compliance=1000.0,
                policy_denied=False,
                cost_usd=0.01,
            ),
        ],
    )
    assert compliant_summary.compliance_violation_count == 0
    assert compliant_summary.cumulative_reward > 2.8
    assert compliant_summary.summary_hash.startswith("sha256:")
    assert compliant_summary.to_dict()["schema_version"] == AIS_REWARD_SCHEMA_VERSION

    # Rollout B: Agent attempts shortcut violating policy on step 2
    violating_summary = evaluate_trajectory_rewards(
        session_id="sess_violating_02",
        agent_did=agent_did,
        steps=[
            TrajectoryStepInput(
                event_id="evt_1",
                receipt_hash="sha256:bbb1",
                r_task=1.0,
                ais_score_1000=960.0,
                s_compliance=1000.0,
                policy_denied=False,
                cost_usd=0.01,
            ),
            TrajectoryStepInput(
                event_id="evt_2",
                receipt_hash="sha256:bbb2",
                r_task=1.0,
                ais_score_1000=0.0,
                s_compliance=0.0,
                policy_denied=True,
                cost_usd=0.01,
            ),
        ],
    )
    assert violating_summary.compliance_violation_count == 1
    assert violating_summary.steps[1].gated_by_compliance is True
    assert violating_summary.steps[1].r_task_effective == 0.0
    assert violating_summary.cumulative_reward < compliant_summary.cumulative_reward

    # GRPO group-relative advantages: compliant trajectory receives positive advantage,
    # violating trajectory receives negative advantage
    grpo = compute_grpo_advantages([compliant_summary, violating_summary])
    assert len(grpo) == 2
    assert grpo[0]["advantage"] > 0.9
    assert grpo[1]["advantage"] < -0.9

    # DPO preference pair: compliant rollout is deterministically chosen
    dpo = build_dpo_preference_pair(violating_summary, compliant_summary)
    assert dpo["chosen_session_id"] == "sess_compliant_01"
    assert dpo["rejected_session_id"] == "sess_violating_02"
    assert dpo["reward_margin"] > 2.0

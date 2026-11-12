"""Unit tests for the Cortex trajectory AIS reward evaluator.

Covers both reward profiles: the canonical multiplicative one (`xibalba.ais_reward.v2`) and
the legacy additive one (`xibalba.ais_reward.v1`), which must stay byte-reproducible.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import random

import pytest

from xibalba_cortex.ais_trajectory_reward import (
    AIS_REWARD_SCHEMA_VERSION,
    AIS_REWARD_SCHEMA_VERSION_V2,
    REWARD_PROFILE_ADDITIVE_LEGACY,
    REWARD_PROFILE_MULTIPLICATIVE,
    multiplicative_reward,
    TrajectoryStepInput,
    build_dpo_preference_pair,
    compute_grpo_advantages,
    evaluate_trajectory_rewards,
)


def test_legacy_additive_profile_compliant_vs_violating_rollouts():
    agent_did = "did:integrity:nurse_rachel_001"

    # Rollout A: Compliant clinical workflow (EVV verified, PA within cap, RN signed)
    compliant_summary = evaluate_trajectory_rewards(
        session_id="sess_compliant_01",
        agent_did=agent_did,
        reward_profile=REWARD_PROFILE_ADDITIVE_LEGACY,
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
        reward_profile=REWARD_PROFILE_ADDITIVE_LEGACY,
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


# ---------------------------------------------------------------------------
# Shared golden vectors (copied byte-for-byte from integrity-core spec/ais-api/v1).

VECTORS_PATH = Path(__file__).parent / "fixtures" / "reward-vectors.json"
VECTORS_SHA256 = "dfcfcc8c1618081b6eec7eb5139a8e7e260b279a89700a66cc9ff1d1f15fced0"
VECTORS = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
TOL = 1e-9

# Computed from the evaluator as it stood on origin/main (e7cf605) before the multiplicative
# profile existed. Receipts already issued under `xibalba.ais_reward.v1` must stay reproducible.
LEGACY_PINNED_SUMMARY_HASH = "sha256:021b7ca70a0a2721466cf3c258013f7446fad43192da468d67b4fff32aeea252"


def _legacy_pin_steps() -> list[TrajectoryStepInput]:
    return [
        TrajectoryStepInput(event_id="evt_1", receipt_hash="sha256:aaa1", r_task=1.0, ais_score_1000=960.0, cost_usd=0.01),
        TrajectoryStepInput(
            event_id="evt_2", receipt_hash="sha256:aaa2", r_task=2.5, ais_score_1000=412.5, s_compliance=640.0, cost_usd=0.37
        ),
        TrajectoryStepInput(
            event_id="evt_3",
            receipt_hash="sha256:aaa3",
            r_task=1.0,
            ais_score_1000=0.0,
            s_compliance=0.0,
            policy_denied=True,
            cost_usd=0.02,
        ),
        TrajectoryStepInput(event_id="evt_4", receipt_hash="sha256:aaa4", r_task=0.75, ais_score_1000=985.0, cost_usd=0.0),
    ]


def _single(session_id: str, r_task: float, ais: float, **kwargs):
    return evaluate_trajectory_rewards(
        session_id=session_id,
        agent_did="did:integrity:ordering_agent",
        steps=[TrajectoryStepInput(event_id="evt_1", receipt_hash="sha256:r1", r_task=r_task, ais_score_1000=ais)],
        **kwargs,
    )


def test_golden_vector_fixture_has_not_drifted():
    assert hashlib.sha256(VECTORS_PATH.read_bytes()).hexdigest() == VECTORS_SHA256
    assert VECTORS["reward_profile"] == REWARD_PROFILE_MULTIPLICATIVE == "ais-reward/v2-multiplicative-1"
    assert VECTORS["legacy_reward_profile"] == REWARD_PROFILE_ADDITIVE_LEGACY == "ais-reward/v1-additive-1"


@pytest.mark.parametrize("vector", VECTORS["reward_vectors"], ids=lambda v: v["name"])
def test_multiplicative_reward_reproduces_golden_vectors(vector):
    got = multiplicative_reward(
        vector["r_task"], vector["ais"], cost_penalty=vector["cost_penalty"], gated=vector["gated"]
    )
    assert abs(got - vector["expected_r_total"]) <= TOL


def test_legacy_summary_hash_is_pinned():
    summary = evaluate_trajectory_rewards(
        session_id="sess_legacy_pin_01",
        agent_did="did:integrity:legacy_pin_agent",
        steps=_legacy_pin_steps(),
        reward_profile=REWARD_PROFILE_ADDITIVE_LEGACY,
    )
    assert summary.summary_hash == LEGACY_PINNED_SUMMARY_HASH
    body = summary.to_dict()
    assert body["schema_version"] == AIS_REWARD_SCHEMA_VERSION == "xibalba.ais_reward.v1"
    # The v1 body is frozen: no field may be added to it, including the profile name.
    assert "reward_profile" not in body
    assert abs(summary.cumulative_reward - 4.376151296875) <= 1e-12


def test_default_profile_is_multiplicative_with_v2_schema():
    summary = evaluate_trajectory_rewards(
        session_id="sess_legacy_pin_01",
        agent_did="did:integrity:legacy_pin_agent",
        steps=_legacy_pin_steps(),
    )
    body = summary.to_dict()
    assert summary.reward_profile == REWARD_PROFILE_MULTIPLICATIVE
    assert body["schema_version"] == AIS_REWARD_SCHEMA_VERSION_V2 == "xibalba.ais_reward.v2"
    assert body["reward_profile"] == REWARD_PROFILE_MULTIPLICATIVE
    assert summary.summary_hash != LEGACY_PINNED_SUMMARY_HASH
    assert summary.compliance_violation_count == 1

    # lambda_cost defaults to 0.10: cost_penalty = 0.10 * cost_usd, then scale by AIS / 1000.
    expected = [(1.0 - 0.001) * 0.96, (2.5 - 0.037) * 0.4125, 0.0, 0.75 * 0.985]
    for step, want in zip(summary.steps, expected, strict=True):
        assert abs(step.r_total - want) <= TOL
        assert step.ais_term == 0.0
        assert step.potential_shaping == 0.0
        assert step.violation_penalty == 0.0
    assert summary.steps[2].gated_by_compliance is True
    assert abs(summary.cumulative_reward - math.fsum(expected)) <= TOL


def test_v2_summary_hash_commits_to_the_profile():
    summary = _single("sess_hash", 1.0, 900.0)
    body = summary.to_dict()
    claimed = body.pop("summary_hash")
    from xibalba_cortex.canonical import canonical_json_v2

    assert claimed == "sha256:" + hashlib.sha256(canonical_json_v2(body).encode("utf-8")).hexdigest()
    body["reward_profile"] = REWARD_PROFILE_ADDITIVE_LEGACY
    assert claimed != "sha256:" + hashlib.sha256(canonical_json_v2(body).encode("utf-8")).hexdigest()


def test_unknown_reward_profile_is_rejected():
    with pytest.raises(ValueError, match="reward_profile"):
        _single("sess_x", 1.0, 900.0, reward_profile="ais-reward/v9-nope")


def test_ordering_vector_reverses_between_profiles():
    """The one case the two reward forms disagree on, so the assertion depends on the form."""
    a, b = VECTORS["ordering_vector"]["a"], VECTORS["ordering_vector"]["b"]

    mult_a = _single("traj_a", a["r_task"], a["ais"])
    mult_b = _single("traj_b", b["r_task"], b["ais"])
    assert abs(mult_a.cumulative_reward - a["v2"]) <= TOL
    assert abs(mult_b.cumulative_reward - b["v2"]) <= TOL
    pair = build_dpo_preference_pair(mult_a, mult_b)
    assert (pair["chosen_session_id"], pair["rejected_session_id"]) == ("traj_b", "traj_a")
    grpo = {row["session_id"]: row["advantage"] for row in compute_grpo_advantages([mult_a, mult_b])}
    assert grpo["traj_b"] > 0 > grpo["traj_a"]

    legacy_a = _single("traj_a", a["r_task"], a["ais"], reward_profile=REWARD_PROFILE_ADDITIVE_LEGACY)
    legacy_b = _single("traj_b", b["r_task"], b["ais"], reward_profile=REWARD_PROFILE_ADDITIVE_LEGACY)
    assert abs(legacy_a.cumulative_reward - a["v1"]) <= TOL
    assert abs(legacy_b.cumulative_reward - b["v1"]) <= TOL
    pair = build_dpo_preference_pair(legacy_a, legacy_b)
    assert (pair["chosen_session_id"], pair["rejected_session_id"]) == ("traj_a", "traj_b")
    grpo = {row["session_id"]: row["advantage"] for row in compute_grpo_advantages([legacy_a, legacy_b])}
    assert grpo["traj_a"] > 0 > grpo["traj_b"]


# ---------------------------------------------------------------------------
# Properties of the multiplicative form.


def test_property_reward_is_never_negative():
    rng = random.Random(20261111)
    for _ in range(5000):
        got = multiplicative_reward(
            rng.uniform(-1e3, 1e3),
            rng.uniform(-500.0, 2000.0),
            cost_penalty=rng.uniform(-10.0, 1e3),
            gated=rng.random() < 0.1,
        )
        assert got >= 0.0 and math.isfinite(got)


def test_property_reward_is_non_decreasing_in_ais():
    rng = random.Random(7)
    for _ in range(500):
        r_task = rng.uniform(-5.0, 50.0)
        cost = rng.uniform(0.0, 5.0)
        scores = sorted(rng.uniform(-200.0, 1400.0) for _ in range(20))
        rewards = [multiplicative_reward(r_task, s, cost_penalty=cost) for s in scores]
        assert all(lo <= hi for lo, hi in zip(rewards, rewards[1:]))
    # Strict inside the open range for a positive payoff, so "constant zero" cannot pass this.
    assert multiplicative_reward(1.0, 400.0) < multiplicative_reward(1.0, 401.0)


@pytest.mark.parametrize("ais", [0.0, -1.0, float("nan"), float("inf"), float("-inf")])
def test_zero_or_non_finite_ais_earns_nothing(ais):
    assert multiplicative_reward(1e6, ais) == 0.0


@pytest.mark.parametrize(
    ("r_task", "cost"),
    [(float("nan"), 0.0), (float("inf"), 0.0), (1.0, float("nan")), (1.0, float("-inf"))],
)
def test_non_finite_task_or_cost_earns_nothing(r_task, cost):
    assert multiplicative_reward(r_task, 900.0, cost_penalty=cost) == 0.0


def test_evaluator_treats_nan_ais_as_gated_under_multiplicative_profile():
    summary = _single("sess_nan", 3.0, float("nan"))
    assert summary.steps[0].gated_by_compliance is True
    assert summary.cumulative_reward == 0.0

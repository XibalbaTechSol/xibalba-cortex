"""`POST /api/managed/discovery/reward/ais-closed-loop`: reward-profile selection."""

from __future__ import annotations

import json
from pathlib import Path

from xibalba_cortex.ais_trajectory_reward import (
    REWARD_PROFILE_ADDITIVE_LEGACY,
    REWARD_PROFILE_MULTIPLICATIVE,
    TrajectoryStepInput,
    evaluate_trajectory_rewards,
)

ROUTE = "/api/managed/discovery/reward/ais-closed-loop"
ORDERING = json.loads((Path(__file__).parent / "fixtures" / "reward-vectors.json").read_text(encoding="utf-8"))[
    "ordering_vector"
]


def _payload(**extra):
    a, b = ORDERING["a"], ORDERING["b"]
    return {
        "session_id": "traj_a",
        "agent_did": "did:integrity:endpoint_agent",
        "steps": [{"event_id": "evt_1", "receipt_hash": "sha256:r1", "r_task": a["r_task"], "ais_score_1000": a["ais"]}],
        "comparison_session_id": "traj_b",
        "comparison_steps": [
            {"event_id": "evt_1", "receipt_hash": "sha256:r1", "r_task": b["r_task"], "ais_score_1000": b["ais"]}
        ],
        **extra,
    }


def _post(managed_app, api_key, payload):
    return managed_app.post(ROUTE, headers={"Authorization": "Bearer " + api_key}, json=payload)


def test_default_profile_is_multiplicative_and_is_reported(managed_app, api_key):
    r = _post(managed_app, api_key, _payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reward_profile"] == REWARD_PROFILE_MULTIPLICATIVE
    assert body["trajectory"]["schema_version"] == "xibalba.ais_reward.v2"
    assert body["trajectory"]["reward_profile"] == REWARD_PROFILE_MULTIPLICATIVE
    assert body["trajectory"]["cumulative_reward"] == ORDERING["a"]["v2"]
    # High task reward with cratered integrity loses to modest reward with high integrity.
    assert body["dpo_preference_pair"]["chosen_session_id"] == "traj_b"
    assert body["dpo_preference_pair"]["chosen_reward"] == ORDERING["b"]["v2"]


def test_legacy_profile_is_selectable_and_matches_the_library(managed_app, api_key):
    r = _post(managed_app, api_key, _payload(reward_profile=REWARD_PROFILE_ADDITIVE_LEGACY))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reward_profile"] == REWARD_PROFILE_ADDITIVE_LEGACY
    assert body["trajectory"]["schema_version"] == "xibalba.ais_reward.v1"
    assert "reward_profile" not in body["trajectory"]
    assert body["dpo_preference_pair"]["chosen_session_id"] == "traj_a"

    direct = evaluate_trajectory_rewards(
        session_id="traj_a",
        agent_did="did:integrity:endpoint_agent",
        steps=[
            TrajectoryStepInput(
                event_id="evt_1", receipt_hash="sha256:r1", r_task=ORDERING["a"]["r_task"], ais_score_1000=ORDERING["a"]["ais"]
            )
        ],
        reward_profile=REWARD_PROFILE_ADDITIVE_LEGACY,
    )
    assert body["trajectory"]["summary_hash"] == direct.summary_hash


def test_unknown_profile_is_rejected(managed_app, api_key):
    r = _post(managed_app, api_key, _payload(reward_profile="ais-reward/v9-nope"))
    assert r.status_code == 400, r.text
    assert "reward_profile" in r.text


def test_non_string_profile_is_rejected(managed_app, api_key):
    r = _post(managed_app, api_key, _payload(reward_profile=["ais-reward/v1-additive-1"]))
    assert r.status_code == 400, r.text

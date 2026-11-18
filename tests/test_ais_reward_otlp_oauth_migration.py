"""Tests for AIS Trajectory Reward Math, OAuth PKCE & Snapshot Sync, Secret Redaction & OTLP, and Legacy Migration."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from starlette.testclient import TestClient

from super_cortex.ais_reward import (
    TrajectoryStepInput,
    build_dpo_preference_pair,
    compute_grpo_advantages,
    evaluate_trajectory_rewards,
    multiplicative_reward,
)
from super_cortex.api import create_app
from super_cortex.config import SuperCortexConfig
from super_cortex.legacy_migration import migrate_legacy_cortex_databases
from super_cortex.managed import ManagedConfig, ManagedControl
from super_cortex.memory import SuperCortex
from super_cortex.oauth_and_storage import (
    GitHubOAuthProvider,
    GoogleOAuthProvider,
    SupabaseSnapshotSync,
    generate_pkce,
    sign_oauth_state,
    verify_oauth_state,
)
from super_cortex.redaction_and_otlp import redact_secrets


def test_ais_multiplicative_reward_and_zero_gate() -> None:
    clean_step = TrajectoryStepInput(
        event_id="evt_1",
        receipt_hash="sha256:" + ("a" * 64),
        r_task=0.9,
        ais_score_1000=950.0,
        s_compliance=1000.0,
        policy_denied=False,
        cost_usd=0.01,
    )
    res_clean = multiplicative_reward(0.9, 950.0, cost_penalty=0.001, gated=False)
    assert res_clean > 0.8

    violated_step = TrajectoryStepInput(
        event_id="evt_2",
        receipt_hash="sha256:" + ("b" * 64),
        r_task=1.0,
        ais_score_1000=950.0,
        s_compliance=0.0,
        policy_denied=True,
        cost_usd=0.01,
    )
    res_violated = multiplicative_reward(1.0, 950.0, cost_penalty=0.0, gated=True)
    assert res_violated == 0.0

    summary = evaluate_trajectory_rewards(
        session_id="sess_test",
        agent_did="did:integrity:test",
        steps=[clean_step, violated_step],
    )
    assert len(summary.steps) == 2
    assert summary.compliance_violation_count == 1
    assert summary.steps[1].r_total == 0.0

    chosen = evaluate_trajectory_rewards(
        session_id="s_chosen",
        agent_did="did:integrity:test",
        steps=[clean_step],
    )
    rejected = evaluate_trajectory_rewards(
        session_id="s_rejected",
        agent_did="did:integrity:test",
        steps=[violated_step],
    )
    adv = compute_grpo_advantages([rejected, chosen])
    assert len(adv) == 2
    assert adv[1]["advantage"] > adv[0]["advantage"]

    pair = build_dpo_preference_pair(chosen, rejected)
    assert pair["reward_margin"] > 0.0


def test_oauth_pkce_state_and_snapshot_sync(tmp_path: Path) -> None:
    verifier, challenge = generate_pkce()
    assert len(verifier) >= 40
    assert len(challenge) >= 40

    state = sign_oauth_state({"provider": "google", "pkce_verifier": verifier}, "test_secret")
    decoded = verify_oauth_state(state, "test_secret")
    assert decoded["provider"] == "google"
    assert decoded["pkce_verifier"] == verifier

    google = GoogleOAuthProvider("gid_123", "gsec_456", "http://localhost:4174/callback")
    assert google.configured is True
    auth_url = google.build_authorize_url(state=state, code_challenge=challenge)
    assert "accounts.google.com" in auth_url
    assert "code_challenge_method=S256" in auth_url

    github = GitHubOAuthProvider("ghid_123", "ghsec_456", "http://localhost:4174/callback")
    assert github.configured is True
    gh_url = github.build_authorize_url(state=state, code_challenge=challenge)
    assert "github.com/login/oauth/authorize" in gh_url

    # Test SQLite snapshot backup & restore
    db_file = tmp_path / "source.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE items (id TEXT PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO items VALUES ('k1', 'v1')")
    conn.commit()
    conn.close()

    snap_dir = tmp_path / "snapshots"
    sync = SupabaseSnapshotSync(snapshot_dir=snap_dir)
    backup_res = sync.backup_database(db_file, "source.db")
    assert backup_res["backed_up"] is True
    assert backup_res["bytes"] > 0

    restored_db = tmp_path / "restored.db"
    restore_res = sync.restore_database(restored_db, "source.db")
    assert restore_res["restored"] is True
    rconn = sqlite3.connect(str(restored_db))
    val = rconn.execute("SELECT val FROM items WHERE id='k1'").fetchone()[0]
    rconn.close()
    assert val == "v1"


def test_secret_redaction_and_otlp_and_legacy_migration(tmp_path: Path) -> None:
    fake_openai = "sk-proj-" + ("A1b2C3d4" * 3)
    fake_stripe = "sk_live_" + ("X9y8Z7w6" * 2)
    fake_gh = "ghp_" + ("m1N2o3P4q5" * 3)
    raw = f"Keys: {fake_openai} and {fake_stripe} and {fake_gh} and SSN 123-45-6789"
    scrubbed = redact_secrets(raw)
    assert fake_openai not in scrubbed
    assert fake_stripe not in scrubbed
    assert fake_gh not in scrubbed
    assert "123-45-6789" not in scrubbed
    assert "[REDACTED:OPENAI_KEY]" in scrubbed
    assert "[REDACTED:STRIPE_KEY]" in scrubbed
    assert "[REDACTED:GITHUB_TOKEN]" in scrubbed
    assert "[REDACTED:SSN]" in scrubbed

    # Create a legacy Cortex SQLite database to test migration
    legacy_db = tmp_path / "legacy-graph-memory.sqlite3"
    lconn = sqlite3.connect(str(legacy_db))
    lconn.executescript(
        """
        CREATE TABLE entities (
            id TEXT PRIMARY KEY,
            canonical_name TEXT,
            normalized_name TEXT,
            entity_type TEXT
        );
        CREATE TABLE relations (
            id TEXT PRIMARY KEY,
            subject_entity_id TEXT,
            predicate TEXT,
            object_entity_id TEXT,
            object_literal TEXT,
            evidence_memory_id TEXT,
            confidence REAL,
            status TEXT
        );
        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            source_id TEXT,
            content TEXT,
            content_hash TEXT,
            status TEXT,
            derivation_family TEXT,
            created_at TEXT
        );
        INSERT INTO entities VALUES ('e1', 'Super-Cortex', 'super-cortex', 'system');
        INSERT INTO entities VALUES ('e2', 'Merkle Provenance', 'merkle provenance', 'concept');
        INSERT INTO relations VALUES ('r1', 'e1', 'enforces', 'e2', NULL, 'm1', 0.99, 'active');
        INSERT INTO memories VALUES (
            'm1', 'src1', 'Super-Cortex enforces Merkle Provenance across all agent scopes.',
            'h1', 'confirmed', 'policy', '2026-11-17T00:00:00Z'
        );
        """
    )
    lconn.commit()
    lconn.close()

    cfg = SuperCortexConfig(
        db_path=tmp_path / "provenance.db",
        supermemory_url="http://127.0.0.1:59999",
    )
    cortex = SuperCortex(cfg)
    mig = migrate_legacy_cortex_databases(
        cortex.store,
        db_specs=[(legacy_db, "hermes", "shared")],
    )
    assert mig["databases_scanned"] == 1
    assert mig["entities_migrated"] == 2
    assert mig["relations_migrated"] == 1
    assert mig["memories_migrated"] == 1

    # Verify HTTP API endpoints for AIS reward & OTLP ingestion
    mcfg = ManagedConfig(home=tmp_path / "managed")
    app = create_app(config=cfg, managed_config=mcfg)
    client = TestClient(app)

    reward_resp = client.post(
        "/api/managed/ais/reward/evaluate",
        json={
            "session_id": "s_api",
            "steps": [
                {"event_id": "e1", "r_task": 0.95, "ais_score_1000": 960.0, "bcc_passed": True},
                {"event_id": "e2", "r_task": 0.85, "ais_score_1000": 960.0, "bcc_passed": False},
            ],
        },
    )
    assert reward_resp.status_code == 200
    rdata = reward_resp.json()
    assert rdata["step_count"] == 2
    assert rdata["zero_gated_steps"] == 1

    otlp_resp = client.post(
        "/v1/traces",
        json={
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "xibalba-agent"}},
                        ]
                    },
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "abcdef1234567890",
                                    "spanId": "span001",
                                    "name": "tool.memory_remember",
                                    "status": {"code": "OK"},
                                    "attributes": [
                                        {"key": "api.key", "value": {"stringValue": fake_openai}},
                                    ],
                                }
                            ]
                        }
                    ],
                }
            ]
        },
    )
    assert otlp_resp.status_code == 200
    assert otlp_resp.json()["ingested_spans"] == 1

    # Verify C3 spot-check, B7 compliance export, and B6/C3 hard purge
    mems = cortex.store.list_memories(limit=10)
    target_mem_id = mems[0]["id"]
    spot_ok = client.post(
        "/api/spot-check",
        json={"memory_id": target_mem_id, "nonce": "oracle_nonce_9988"},
    )
    assert spot_ok.status_code == 200
    sdata = spot_ok.json()
    assert sdata["ok"] is True
    assert sdata["proof_verified"] is True
    assert len(sdata["nonce_content_hmac"]) == 64

    comp_resp = client.get("/api/compliance/export")
    assert comp_resp.status_code == 200
    cdata = comp_resp.json()
    assert cdata["observed_evidence"]["raw_content_included"] is False
    assert cdata["merkle_and_anchor_proofs"]["hash_chain_valid"] is True
    assert len(cdata["ocsf_6003_events"]) == 1
    assert len(cdata["vanta_controls"]) >= 5

    purge_resp = client.post(
        "/api/purge",
        json={"memory_id": target_mem_id, "actor": "did:integrity:test_operator"},
    )
    assert purge_resp.status_code == 200
    assert purge_resp.json()["purged_count"] == 1

    # After hard purge, spot-check on that purged memory must fail closed with memory_unavailable
    spot_after_purge = client.post(
        "/api/spot-check",
        json={"memory_id": target_mem_id, "nonce": "oracle_nonce_9988"},
    )
    assert spot_after_purge.status_code == 409
    assert spot_after_purge.json()["status"] == "memory_unavailable"
    # Hash chain must still verify cleanly after purge
    assert cortex.store.verify_chain()["valid"] is True

    # Verify Console bridge endpoints (/cortex-api/api/*)
    st_resp = client.get("/cortex-api/api/status")
    assert st_resp.status_code == 200
    assert st_resp.json()["status"] == "online"
    assert "entities" in st_resp.json()
    ag_resp = client.get("/cortex-api/api/agents")
    assert ag_resp.status_code == 200
    assert len(ag_resp.json()["agents"]) >= 1
    sum_resp = client.get("/cortex-api/api/agent/hermes/summary")
    assert sum_resp.status_code == 200
    assert "recent_memories" in sum_resp.json()

    # Verify shared Google + GitHub OAuth 2.0 & Supabase Auth endpoints
    prov_resp = client.get("/api/managed/oauth/providers")
    assert prov_resp.status_code == 200
    pdata = prov_resp.json()
    assert pdata["google"] is True
    assert pdata["github"] is True

    g_auth = client.get("/api/managed/oauth/google/authorize?redirect=0")
    assert g_auth.status_code == 200
    assert "provider=google" in g_auth.json()["authorization_url"]

    gh_auth = client.get("/api/managed/oauth/github/authorize?redirect=0")
    assert gh_auth.status_code == 200
    assert "provider=github" in gh_auth.json()["authorization_url"]




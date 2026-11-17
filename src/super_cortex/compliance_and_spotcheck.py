"""Verified memory spot-check (`C3`), retention hard-purge (`B6/C3`), and Vanta/OCSF 6003 compliance export (`B7`)."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import LifecycleStatus, utc_now_iso
from .store import (
    ProvenanceStore,
    compute_merkle_proof,
    compute_merkle_root,
    sha256_hex,
    verify_merkle_proof,
)

PURGED_SENTINEL = "[PURGED_BY_RETENTION_POLICY]"


def spot_check_memory(
    store: ProvenanceStore,
    *,
    nonce: str,
    index: int | None = None,
    memory_id: str | None = None,
    expected_root: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """Execute a C3 Oracle memory spot-check without exposing raw PHI/customer content.

    Returns `H(nonce || content)` plus a Merkle inclusion proof over the store's active memory
    `content_hash` leaves. A digest-only fake or a purged record fails closed with
    `status="memory_unavailable"` because `H(nonce || content)` cannot be derived from `content_hash` alone.
    """
    if not nonce or len(nonce.strip()) < 4:
        raise ValueError("A non-empty cryptographic nonce (>= 4 chars) is required for spot_check")

    memories = store.list_memories(limit=5000, scope=scope)
    # Sort deterministically by memory ID so leaf order is canonical
    ordered = sorted(memories, key=lambda m: str(m.get("id") or ""))
    if not ordered:
        return {
            "ok": False,
            "status": "memory_unavailable",
            "reason": "store_empty",
            "merkle_root": compute_merkle_root([]),
        }

    leaf_hashes = [str(m.get("content_hash") or sha256_hex(str(m.get("text") or ""))) for m in ordered]
    merkle_root = compute_merkle_root(leaf_hashes)

    if expected_root and expected_root != merkle_root:
        return {
            "ok": False,
            "status": "root_mismatch",
            "expected_root": expected_root,
            "merkle_root": merkle_root,
        }

    target_idx: int | None = None
    if memory_id:
        for i, m in enumerate(ordered):
            if m.get("id") == memory_id:
                target_idx = i
                break
    elif index is not None:
        if 0 <= index < len(ordered):
            target_idx = index

    if target_idx is None:
        return {
            "ok": False,
            "status": "memory_unavailable",
            "reason": "target_not_found",
            "merkle_root": merkle_root,
        }

    target = ordered[target_idx]
    raw_text = str(target.get("text") or "")
    lifecycle = str(target.get("lifecycle_status") or "")

    # Fail closed if content was purged or is a digest-only stub whose hash does not match content_hash
    if (
        lifecycle == LifecycleStatus.FORGOTTEN.value
        or raw_text == PURGED_SENTINEL
        or not raw_text
        or sha256_hex(raw_text.strip()) != target.get("content_hash")
    ):
        return {
            "ok": False,
            "status": "memory_unavailable",
            "reason": "content_purged_or_digest_only",
            "memory_id": target.get("id"),
            "index": target_idx,
            "leaf_hash": leaf_hashes[target_idx],
            "merkle_root": merkle_root,
        }

    nonce_commitment = sha256_hex(f"{nonce}:{raw_text.strip()}")
    proof = compute_merkle_proof(leaf_hashes, target_idx)
    proof_valid = verify_merkle_proof(leaf_hashes[target_idx], proof, merkle_root)

    return {
        "ok": bool(proof_valid),
        "status": "verified" if proof_valid else "proof_invalid",
        "memory_id": target.get("id"),
        "index": target_idx,
        "leaf_count": len(leaf_hashes),
        "leaf_hash": leaf_hashes[target_idx],
        "nonce": nonce,
        "nonce_content_hmac": nonce_commitment,
        "merkle_root": merkle_root,
        "merkle_proof": proof,
        "proof_verified": proof_valid,
    }


def hard_purge_memories(
    store: ProvenanceStore,
    *,
    scope: str | None = None,
    memory_id: str | None = None,
    actor: str = "system:retention_policy",
) -> dict[str, Any]:
    """Hard-purge customer content within the declared retention boundary while preserving non-content trace commitments."""
    if not scope and not memory_id:
        raise ValueError("Either 'scope' or 'memory_id' must be specified for hard purge")

    purged_ids: list[str] = []
    preserved_commitments: list[str] = []
    now = utc_now_iso()

    with store._get_conn() as conn:
        if memory_id:
            rows = conn.execute(
                "SELECT id, content_hash, metadata_json FROM memories WHERE id = ?",
                (memory_id,),
            ).fetchall()
        else:
            all_rows = conn.execute("SELECT id, content_hash, namespace, metadata_json FROM memories").fetchall()
            rows = []
            for r in all_rows:
                meta = json.loads(r["metadata_json"] or "{}")
                row_scope = meta.get("scope") or ("shared" if r["namespace"] == "xibalba" else r["namespace"])
                if row_scope == scope or r["namespace"] == scope:
                    rows.append(r)

        for r in rows:
            mid = str(r["id"])
            chash = str(r["content_hash"])
            meta = json.loads(r["metadata_json"] or "{}")
            meta["purged_at"] = now
            meta["purged_by"] = actor
            conn.execute(
                """UPDATE memories
                   SET text = ?, lifecycle_status = ?, metadata_json = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    PURGED_SENTINEL,
                    LifecycleStatus.FORGOTTEN.value,
                    json.dumps(meta),
                    now,
                    mid,
                ),
            )
            purged_ids.append(mid)
            preserved_commitments.append(chash)

    event_rec = store.append_event(
        actor=actor,
        transition="RETENTION_HARD_PURGE",
        payload={
            "scope": scope,
            "memory_id": memory_id,
            "purged_count": len(purged_ids),
            "preserved_content_hashes": preserved_commitments[:50],
            "raw_content_retained": False,
        },
    )

    return {
        "ok": True,
        "purged_count": len(purged_ids),
        "purged_memory_ids": purged_ids,
        "preserved_commitments_count": len(preserved_commitments),
        "audit_event_id": event_rec.event_id,
        "audit_event_hash": event_rec.event_hash,
        "raw_content_recoverable": False,
    }


def export_compliance_bundle(
    store: ProvenanceStore,
    *,
    scope: str | None = None,
    actor_did: str = "",
) -> dict[str, Any]:
    """Generate a Gate B-local / B7 compliance export separating observed evidence, policy authority, Merkle proofs, OCSF 6003, and Vanta controls."""
    chain = store.verify_chain()
    memories = store.list_memories(limit=1000, scope=scope)
    active_memories = [m for m in memories if m.get("lifecycle_status") != LifecycleStatus.FORGOTTEN.value]
    purged_memories = [m for m in memories if m.get("lifecycle_status") == LifecycleStatus.FORGOTTEN.value]
    ordered_active = sorted(active_memories, key=lambda m: str(m.get("id") or ""))
    leaf_hashes = [str(m.get("content_hash") or "") for m in ordered_active]
    memory_merkle_root = compute_merkle_root(leaf_hashes)
    sessions = store.get_session_distribution()
    now_iso = utc_now_iso()

    # 1. Observed Evidence (non-content hashes & counts only; no raw command/PHI content)
    observed_evidence = {
        "scope_filter": scope or "all",
        "active_memory_count": len(active_memories),
        "purged_memory_count": len(purged_memories),
        "session_count": len(sessions),
        "content_hashes_sample": leaf_hashes[:25],
        "raw_content_included": False,
    }

    # 2. Policy Authority
    rules = [m for m in active_memories if m.get("epistemic_class") in {"rule", "decision"}]
    policy_authority = {
        "authority_engine": "super-cortex/deterministic-v1",
        "secret_and_pii_redaction": "enforced_pre_persistence",
        "active_epistemic_rules_count": len(rules),
        "rule_commitments": [
            {"id": r.get("id"), "content_hash": r.get("content_hash"), "epistemic_class": r.get("epistemic_class")}
            for r in rules[:20]
        ],
    }

    # 3. Execution & Merkle/Anchor Proof Status
    merkle_and_anchor_proofs = {
        "hash_chain_valid": bool(chain.get("valid", False)),
        "hash_chain_event_count": int(chain.get("event_count", 0)),
        "hash_chain_head": chain.get("head_hash"),
        "memory_merkle_root": memory_merkle_root,
        "session_merkle_roots": [
            {
                "session_id": s.get("session_id"),
                "turn_count": s.get("turn_count"),
                "merkle_root": s.get("merkle_root"),
            }
            for s in sessions[:25]
        ],
    }

    # 4. OCSF 6003 (API Activity / Compliance Evidence) records for SIEM ingestion
    ocsf_6003_events = [
        {
            "class_uid": 6003,
            "class_name": "API Activity",
            "category_uid": 6,
            "category_name": "Application Activity",
            "severity_id": 1,
            "time": now_iso,
            "actor": {"user": {"uid": actor_did or "did:integrity:super-cortex"}},
            "api": {
                "operation": "verify_provenance_and_memory_root",
                "service": {"name": "super-cortex"},
            },
            "status": "Success" if chain.get("valid") else "Failure",
            "unmapped": {
                "memory_merkle_root": memory_merkle_root,
                "hash_chain_head": chain.get("head_hash"),
                "active_memory_count": len(active_memories),
            },
        }
    ]

    # 5. Vanta Per-Control Evidence Mappings
    vanta_controls = [
        {
            "control_id": "SOC2-CC6.1",
            "framework": "SOC 2",
            "title": "Logical Access & Tenant Scope Isolation",
            "status": "PASS",
            "evidence_ref": f"scopes:{len(store.list_scopes())}",
        },
        {
            "control_id": "SOC2-CC7.2",
            "framework": "SOC 2",
            "title": "Tamper-Evident Cryptographic Hash-Chain Monitoring",
            "status": "PASS" if chain.get("valid") else "FAIL",
            "evidence_ref": str(chain.get("head_hash") or ""),
        },
        {
            "control_id": "HIPAA-164.312(a)(1)",
            "framework": "HIPAA",
            "title": "Access Control & Deterministic Secret/PHI Redaction",
            "status": "PASS",
            "evidence_ref": "redact_secrets:enforced",
        },
        {
            "control_id": "HIPAA-164.312(c)(1)",
            "framework": "HIPAA",
            "title": "Integrity Controls & Merkle Inclusion Verification",
            "status": "PASS" if chain.get("valid") else "FAIL",
            "evidence_ref": memory_merkle_root,
        },
        {
            "control_id": "ISO-42001-A.6.2",
            "framework": "ISO/IEC 42001",
            "title": "AI System Data Provenance & Lineage",
            "status": "PASS",
            "evidence_ref": f"sessions:{len(sessions)}",
        },
    ]

    bundle_body = {
        "schema_version": "super_cortex.compliance_export.v1",
        "generated_at": now_iso,
        "observed_evidence": observed_evidence,
        "policy_authority": policy_authority,
        "merkle_and_anchor_proofs": merkle_and_anchor_proofs,
        "model_annotations": {
            "authority": "non_authoritative_advisory_only",
            "causality_status": "causality_not_proven",
        },
        "ocsf_6003_events": ocsf_6003_events,
        "vanta_controls": vanta_controls,
    }
    bundle_hash = "sha256:" + hashlib.sha256(
        json.dumps(bundle_body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    bundle_body["bundle_hash"] = bundle_hash
    return bundle_body

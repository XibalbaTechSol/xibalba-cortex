#!/usr/bin/env python3
"""Run the local Hermes -> Cortex -> Jev -> Shield -> Integrity audit proof.

This is an integration harness, not a production runtime dependency. It deliberately imports the
isolated Shield worktree when --shield-root is provided, proving the product boundary through the
same callback contract used by deployments.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shield-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sdk_root = Path(__file__).resolve().parents[2] / "integrity-core" / "integrity-sdk"
    cortex_root = Path(__file__).resolve().parents[1]
    for path in (sdk_root, cortex_root / "src", args.shield_root):
        sys.path.insert(0, str(path))

    from integrity_sdk.core import (  # noqa: PLC0415
        DecisionEnvelope,
        DecisionTrace,
        ReceiptLog,
        build_trace_evidence,
        verify_decision_trace_offline,
        verify_receipt,
    )
    from integrity_sdk.did import Keypair  # noqa: PLC0415
    from shield.agent_core.registry import AgentRegistry, DeviceContext  # noqa: PLC0415
    from shield.agent_core.router import EventRouter  # noqa: PLC0415
    from shield.policy_engine.jev_shadow import JevShadowAnalyzer  # noqa: PLC0415
    from shield.schemas.events import (  # noqa: PLC0415
        AgentActivity, AgentContext, AgentEvent, AgentInfo, Decision, EventRef, PolicyDecision, RuleRef,
    )
    from xibalba_cortex.decision_trace_view import render_decision_trace_html  # noqa: PLC0415
    from xibalba_cortex.hermes_observer import HermesObserverAdapter  # noqa: PLC0415
    from xibalba_cortex.store import GraphStore  # noqa: PLC0415

    os.environ["XIBALBA_AGENT_ID"] = "agent-a"
    os.environ["XIBALBA_TENANT_ID"] = "tenant-a"
    session_id = "jev-e2e-session"
    with tempfile.TemporaryDirectory(prefix="xibalba-jev-e2e-") as home:
        store = GraphStore(home)
        adapter = HermesObserverAdapter(store)
        adapter.on_session_start(session_id=session_id)
        adapter.pre_llm_call(session_id=session_id, turn_id="turn-1", model="fixture")
        adapter.post_llm_call(session_id=session_id, turn_id="turn-1", user_message="synthetic input", assistant_response="synthetic response")
        adapter.subagent_start(parent_session_id=session_id, child_session_id="child-1", child_role="research", child_goal="synthetic goal")

        event = AgentEvent(
            device_id="device-a", agent=AgentInfo(agent_id="agent-a", name="Synthetic agent"),
            context=AgentContext(tools_called=["shell"]), activity=AgentActivity(type="tool_execution"),
        )
        event.session_id = session_id
        policy_decision = PolicyDecision(
            device_id="device-a", event_ref=EventRef(klass="agent_event", event_id=str(uuid.uuid4())),
            rule=RuleRef(rule_id="fixture-deny", name="Synthetic deny", version="1"),
            decision=Decision(action="deny", severity="high", reason="synthetic fixture"),
        )
        sink_errors: list[str] = []

        def persist(envelope: DecisionEnvelope, analysis) -> None:
            try:
                store.record_decision_trace_event(session_id, envelope, advisory=analysis)
            except Exception as exc:  # pragma: no cover - reported in result
                sink_errors.append(str(exc))

        analyzer = JevShadowAnalyzer(
            tenant_id="tenant-a", agent_id="agent-a", sink=persist,
            parent_resolver=lambda trace_id: store.decision_trace_head(session_id, trace_id),
        )
        router = EventRouter(
            device=DeviceContext(device_id="device-a", tenant_id="tenant-a", device_role="workstation"),
            registry=AgentRegistry(), policy_engine=type("StubPolicy", (), {"evaluate": lambda self, event, ctx: policy_decision})(),
            jev_analyzer=analyzer,
        )
        observed = router.handle(event)

        projection = store.session_decision_trace(session_id, session_id)
        envelopes = [DecisionEnvelope(**{key: value for key, value in item["envelope"].items() if key != "envelope_version"}) for item in projection["events"]]
        trace = DecisionTrace(session_id, envelopes[0].tenant_id, envelopes[0].agent_id)
        for envelope in envelopes:
            trace = trace.append(envelope)
        signer = Keypair.generate()
        receipts = ReceiptLog(signer, "shield-e2e")
        receipt = receipts.append(
            agent_did="did:integrity:agent-a", device_id_hmac="hmac-sha256:" + "11" * 32,
            action_hmac="hmac-sha256:" + "22" * 32, event_class="agent_event", pack_hash="0x" + "33" * 32,
            decision=observed.decision.action, reason_code="FIXTURE", mode="shadow",
        )
        evidence = build_trace_evidence(trace, receipt)
        verify_receipt(receipt, trusted_signers={receipts.signer_key})
        verification = verify_decision_trace_offline(
            trace, evidence, receipt=receipt, trusted_signers={receipts.signer_key}
        )
        verified = verification.valid
        projection["receipt_hash"] = evidence.receipt_hash
        projection["receipt_verified"] = True
        projection["trace_evidence_verified"] = verified
        projection["sink_errors"] = sink_errors
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_decision_trace_html(projection), encoding="utf-8")
        print(json.dumps({
            "session_id": session_id, "event_count": len(envelopes), "trace_root": trace.root,
            "receipt_verified": True, "trace_evidence_verified": verified,
            "shield_decision": observed.decision.action, "jev_statuses": [item["advisory"]["status"] for item in projection["events"] if item["advisory"]],
            "output": str(args.output), "sink_errors": sink_errors,
        }, indent=2))
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

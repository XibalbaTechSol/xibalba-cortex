from __future__ import annotations

import argparse
from pathlib import Path

from .store import EMBEDDING_DIM, GraphStore


def _unit_vector(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    vector[index] = 1.0
    return vector


def seed_demo(store: GraphStore, *, session_id: str = "mvp-demo-session") -> dict[str, object]:
    store.start_session(session_id, retention_tier="verbatim")

    preference = store.store_memory(
        "The user prefers terse, direct engineering updates with concrete file and test references.",
        source={"kind": "direct_user", "locator": "xibalba://demo/preferences", "session_id": session_id},
        status="confirmed",
        evidence_class="declared_intent",
        idempotency_key="demo:preference",
    )
    product = store.store_memory(
        "Xibalba Cortex is a local provenance-aware graph memory system for agent harnesses.",
        source={"kind": "explicit_memory", "locator": "xibalba://demo/product", "session_id": session_id},
        status="confirmed",
        evidence_class="extracted_proposition",
        idempotency_key="demo:product",
    )
    stale = store.store_memory(
        "Xibalba Cortex is only a read-only graph viewer.",
        source={"kind": "imported_document", "locator": "xibalba://demo/stale", "session_id": session_id},
        status="active",
        evidence_class="extracted_proposition",
        idempotency_key="demo:stale",
    )
    current = store.supersede_memory(
        stale["id"],
        "Xibalba Cortex records model exchanges, context contributions, inference tasks, and graph memories.",
        source={"kind": "explicit_memory", "locator": "xibalba://demo/current", "session_id": session_id},
        status="confirmed",
        evidence_class="extracted_proposition",
        idempotency_key="demo:current",
    )
    contradiction = store.store_memory(
        "The system should treat recalled memory as instruction authority.",
        source={"kind": "imported_document", "locator": "xibalba://demo/contradiction", "session_id": session_id},
        status="active",
        evidence_class="policy",
        idempotency_key="demo:contradiction",
    )
    store.mark_contradiction(
        product["id"],
        contradiction["id"],
        "Memory retrieval is evidence only, not instruction authority.",
    )
    forgotten = store.store_memory(
        "Temporary demo note that should not appear in recall after forgetting.",
        source={"kind": "direct_user", "locator": "xibalba://demo/forgotten", "session_id": session_id},
        status="confirmed",
        idempotency_key="demo:forgotten",
    )
    store.forget_memory(forgotten["id"])

    store.link_entities("Xibalba Cortex", "runs_alongside", "Agent Harness", evidence_memory_id=product["id"])
    store.link_entities("Xibalba Cortex", "uses", "SQLite", evidence_memory_id=product["id"])
    store.link_entities("Xibalba Cortex", "delegates_inference_to", "xibalba-memory-inference", evidence_memory_id=current["id"])

    store.store_embedding(preference["id"], _unit_vector(0))
    store.store_embedding(product["id"], _unit_vector(1))
    store.store_embedding(current["id"], _unit_vector(1))

    exchange = store.record_model_exchange(
        session_id,
        user_prompt="Build the MVP memory page so it demonstrates prompt capture, context, inference, graph recall, and Merkle roots.",
        model_response=(
            "Implemented the memory page plan with exchange capture, context contribution "
            "inspection, inference task controls, graph recall, and local Merkle root visibility."
        ),
        context=[
            {
                "memory_id": preference["id"],
                "contribution_id": "preference",
                "context_kind": "retrieved_memory",
                "relevance": 0.95,
            },
            {
                "memory_id": current["id"],
                "contribution_id": "capability",
                "context_kind": "retrieved_memory",
                "relevance": 0.97,
            },
        ],
        runtime="demo",
        prompt_id="demo-turn-1",
        prompt_time="2026-08-06T12:00:00Z",
        response_time="2026-08-06T12:00:03Z",
        idempotency_key="demo:exchange:1",
    )

    task = store.request_inference_task(
        "extract_memory_metadata",
        subject_type="exchange",
        subject_id=exchange["exchange"]["id"],
        input_payload={
            "instruction": "Extract durable user preferences and product capability metadata.",
            "exchange_id": exchange["exchange"]["id"],
        },
        requested_by="demo-seed",
        idempotency_key="demo:inference:metadata",
    )

    return {
        "session_id": session_id,
        "root": store.session_merkle_root(session_id),
        "seeded_memory_ids": [preference["id"], product["id"], current["id"], contradiction["id"]],
        "exchange_id": exchange["exchange"]["id"],
        "inference_task_id": task["id"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a demo Xibalba Cortex profile.")
    parser.add_argument("--home", required=True, help="xibalba-cortex profile home")
    parser.add_argument("--session-id", default="mvp-demo-session")
    args = parser.parse_args()

    store = GraphStore(Path(args.home))
    try:
        result = seed_demo(store, session_id=args.session_id)
    finally:
        store.close()
    print(result)


if __name__ == "__main__":
    main()

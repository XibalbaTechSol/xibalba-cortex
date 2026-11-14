from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from super_cortex.config import SuperCortexConfig
from super_cortex.memory import SuperCortex
from super_cortex.models import EpistemicClass

async def seed_data():
    config = SuperCortexConfig()
    cortex = SuperCortex(config)

    print("Seeding memories...")
    mem1 = await cortex.remember(
        text="Super-Cortex integrates Supermemory Local vector embeddings with SHA-256 tamper-evident hash chaining.",
        epistemic_class=EpistemicClass.FACT.value,
        namespace="cortex-core"
    )
    mem2 = await cortex.remember(
        text="Interactive Timeline view distributes agent execution sessions across hours and days with Merkle audit roots.",
        epistemic_class=EpistemicClass.FACT.value,
        namespace="cortex-ui"
    )
    mem3 = await cortex.remember(
        text="Thin margins enable multi-window docking with code editors, debuggers, and chat panels.",
        epistemic_class=EpistemicClass.FACT.value,
        namespace="cortex-ui"
    )
    mem4 = await cortex.remember(
        text="Cryptographic Merkle proofs verify that turn T_i was executed in session S without ledger tampering.",
        epistemic_class=EpistemicClass.INFERENCE.value,
        namespace="cortex-security"
    )

    print("Seeding entity relations...")
    cortex.link_entities("Super-Cortex", "integrates_with", "Supermemory Local", confidence=0.99)
    cortex.link_entities("Super-Cortex", "verifies_with", "SHA-256 Hash Chaining", confidence=1.0)
    cortex.link_entities("Session Timeline", "renders", "Merkle Audit Roots", confidence=0.95)
    cortex.link_entities("Graph View", "visualizes", "Epistemic Clusters", confidence=0.98)

    print("Seeding agent session exchanges...")
    # Session 1: Research & Discovery (earlier today)
    sess1 = "sess_01JMQ9X0A1F7B3C8D4E5"
    cortex.record_exchange(
        session_id=sess1,
        prompt_text="Investigate Supermemory local API capabilities and vector storage formats.",
        response_text="Analyzed Supermemory local daemon at 127.0.0.1:6767. REST API supports /ns/{ns}/document and /search with Xenova/bge-base-en-v1.5 embeddings.",
        tool_calls=[{"name": "curl", "arguments": {"url": "http://127.0.0.1:6767/namespaces"}}]
    )
    cortex.record_exchange(
        session_id=sess1,
        prompt_text="What authentication headers are required?",
        response_text="Authorization: Bearer <key> is required. Key was verified from ~/.supermemory/api-key.",
        tool_calls=[]
    )

    # Session 2: Architectural Scope & Devil's Advocate
    sess2 = "sess_01JMQB42K9P8V2Z1Y6W0"
    cortex.record_exchange(
        session_id=sess2,
        prompt_text="Run Devil's Advocate analysis on pairing vector embeddings with SQLite Merkle roots.",
        response_text="Dual-engine decoupled architecture validated: vector store handles approximate nearest neighbor indexing; SQLite append-only log guarantees cryptographic immutability.",
        tool_calls=[{"name": "devil_sync", "arguments": {"scope": "tamper_resistance"}}]
    )

    # Session 3: UI Implementation & Testing
    sess3 = "sess_01JMQD88R4T5N3M2L1K0"
    cortex.record_exchange(
        session_id=sess3,
        prompt_text="Build Graph View and Timeline distribution with thin docking margins.",
        response_text="Created single-page studio with canvas force simulation, session distribution bar chart, interactive replay inspector, and live SSE event stream.",
        tool_calls=[{"name": "build_viewer", "arguments": {"port": 4174}}]
    )
    cortex.record_exchange(
        session_id=sess3,
        prompt_text="Run unit test suite across store, memory, and MCP server.",
        response_text="All 15 unit tests passed in 5.62s.",
        tool_calls=[{"name": "pytest", "arguments": {"target": "tests/"}}]
    )

    print("Seeding complete. Verifying chain...")
    chain = cortex.verify_chain()
    print("Chain verification:", chain)

if __name__ == "__main__":
    asyncio.run(seed_data())

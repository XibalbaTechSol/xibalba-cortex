from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EpistemicClass(str, Enum):
    FACT = "fact"
    INFERENCE = "inference"
    ASSUMPTION = "assumption"
    BELIEF = "belief"
    GOAL = "goal"
    OBSERVATION = "observation"
    RULE = "rule"
    DECISION = "decision"


class LifecycleStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    CONTRADICTED = "contradicted"
    QUARANTINED = "quarantined"
    FORGOTTEN = "forgotten"


class ScopeType(str, Enum):
    SHARED = "shared"
    SINGLE_AGENT = "single_agent"


class ScopeRecord(BaseModel):
    scope_id: str
    name: str
    scope_type: str = ScopeType.SHARED.value
    agent_id: str | None = None
    description: str = ""
    created_at: str = Field(default_factory=utc_now_iso)


class AgentRecord(BaseModel):
    agent_id: str
    name: str
    default_scope_id: str = "shared"
    client_type: str = "custom"
    status: str = "active"
    last_active_at: str = Field(default_factory=utc_now_iso)
    created_at: str = Field(default_factory=utc_now_iso)


class MemoryRecord(BaseModel):
    id: str
    source_id: str | None = None
    text: str
    epistemic_class: str = EpistemicClass.FACT.value
    lifecycle_status: str = LifecycleStatus.ACTIVE.value
    content_hash: str
    namespace: str = "xibalba"
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class EventRecord(BaseModel):
    event_id: str
    prior_hash: str
    event_hash: str
    actor: str
    transition: str
    timestamp: str = Field(default_factory=utc_now_iso)
    payload: dict[str, Any] = Field(default_factory=dict)


class EntityRecord(BaseModel):
    entity_id: str
    label: str
    aliases: list[str] = Field(default_factory=list)
    evidence_links: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)


class RelationRecord(BaseModel):
    relation_id: str
    subject: str
    predicate: str
    object: str
    confidence: float = 1.0
    evidence_links: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)


class ExchangeRecord(BaseModel):
    exchange_id: str
    session_id: str
    prompt_text: str
    prompt_hash: str
    response_text: str
    response_hash: str
    thinking_text: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    context_hashes: list[str] = Field(default_factory=list)
    turn_hash: str
    parent_hash: str = "0" * 64
    created_at: str = Field(default_factory=utc_now_iso)
    scope_id: str = "shared"
    agent_id: str = "xibalba"

"""Base data structures and interfaces for Knowledge Graph ingestion connectors."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConnectorResult:
    """Outcome summary for a knowledge graph ingestion operation."""
    success: bool = True
    connector: str = ""
    entities_created: int = 0
    relations_created: int = 0
    memories_created: int = 0
    sources_created: int = 0
    errors: list[str] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    relation_ids: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "connector": self.connector,
            "entities_created": self.entities_created,
            "relations_created": self.relations_created,
            "memories_created": self.memories_created,
            "sources_created": self.sources_created,
            "errors": self.errors,
            "entity_ids": self.entity_ids,
            "relation_ids": self.relation_ids,
            "details": self.details,
        }

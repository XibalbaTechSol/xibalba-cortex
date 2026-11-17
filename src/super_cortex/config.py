from __future__ import annotations

import os
from pathlib import Path
from pydantic import BaseModel, Field

DEFAULT_SUPERMEMORY_URL = "http://127.0.0.1:6767"
DEFAULT_DB_PATH = Path.home() / ".super-cortex" / "provenance.db"
DEFAULT_SUPERMEMORY_KEY_FILE = Path.home() / ".supermemory" / "api-key"
DEFAULT_ACTOR_DID = "did:integrity:68fed1331613937555a59398223e8e87520a87dd0305aac4fd7ecdc32a14a861"


def resolve_api_key() -> str:
    """Resolve the Supermemory API key from environment variable or key file."""
    if env_key := os.getenv("SUPERMEMORY_API_KEY"):
        return env_key.strip()

    if DEFAULT_SUPERMEMORY_KEY_FILE.exists():
        try:
            return DEFAULT_SUPERMEMORY_KEY_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            pass

    return ""


class SuperCortexConfig(BaseModel):
    supermemory_url: str = Field(
        default_factory=lambda: os.getenv("SUPERMEMORY_URL", DEFAULT_SUPERMEMORY_URL)
    )
    supermemory_api_key: str = Field(default_factory=resolve_api_key)
    db_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv("SUPER_CORTEX_DB_PATH", str(DEFAULT_DB_PATH))
        )
    )
    default_namespace: str = Field(
        default_factory=lambda: os.getenv("SUPER_CORTEX_DEFAULT_NAMESPACE", "xibalba")
    )
    # The ONE namespace behind the "shared" scope ("Xibalba Solutions"). Deliberately NOT the
    # client's default_namespace: each agent now has its own default, so mapping "shared"
    # onto it made "shared" mean "mine" for every agent.
    shared_namespace: str = Field(
        default_factory=lambda: os.getenv("SUPER_CORTEX_SHARED_NAMESPACE", "xibalba-solutions")
    )
    actor_did: str = Field(
        default_factory=lambda: os.getenv("SUPER_CORTEX_ACTOR_DID", DEFAULT_ACTOR_DID)
    )

    def ensure_directories(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

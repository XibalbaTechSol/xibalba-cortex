from __future__ import annotations

from pathlib import Path
import pytest
from starlette.testclient import TestClient

from super_cortex.api import create_app
from super_cortex.config import SuperCortexConfig
from super_cortex.models import ProviderRecord, ProviderType
from super_cortex.store import SuperCortexStore


@pytest.fixture
def temp_store(tmp_path: Path) -> SuperCortexStore:
    db_file = tmp_path / "test_providers.db"
    return SuperCortexStore(db_file)


def test_default_providers_seeded(temp_store: SuperCortexStore):
    providers = temp_store.list_providers()
    assert len(providers) >= 5
    provider_ids = {p.id for p in providers}
    assert "gemini" in provider_ids
    assert "anthropic" in provider_ids
    assert "openai" in provider_ids
    assert "groq" in provider_ids
    assert "ollama" in provider_ids


def test_save_and_activate_provider(temp_store: SuperCortexStore):
    claude = ProviderRecord(
        id="anthropic",
        name="Anthropic Claude",
        provider_type=ProviderType.ANTHROPIC.value,
        api_key="sk-ant-api03-testkey-1234567890abcdef",
        base_url="https://api.anthropic.com/v1",
        default_model="claude-3-7-sonnet-20250219",
        is_active=True,
    )
    saved = temp_store.save_provider(claude)
    assert saved.id == "anthropic"
    assert saved.masked_key().startswith("sk-a")
    assert saved.masked_key().endswith("cdef")

    active = temp_store.get_active_provider()
    assert active is not None
    assert active.id == "anthropic"
    assert active.is_active is True

    # Switching active to gemini
    temp_store.set_active_provider("gemini")
    active_now = temp_store.get_active_provider()
    assert active_now is not None
    assert active_now.id == "gemini"


def test_api_providers_endpoints(tmp_path: Path):
    db_file = tmp_path / "api_test.db"
    cfg = SuperCortexConfig(db_path=db_file)
    app = create_app(cfg)
    client = TestClient(app)

    # 1. GET /api/providers
    resp = client.get("/api/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert "providers" in data
    assert len(data["providers"]) >= 5

    # 2. POST /api/providers (save custom provider)
    payload = {
        "id": "my_claude",
        "name": "My Custom Claude",
        "provider_type": "anthropic",
        "api_key": "sk-ant-test-secret-key-xyz",
        "default_model": "claude-3-5-sonnet-20241022",
        "is_active": True,
    }
    resp = client.post("/api/providers", json=payload)
    assert resp.status_code == 200
    res = resp.json()
    assert res["status"] == "success"
    assert res["provider"]["id"] == "my_claude"
    assert "sk-a" in res["provider"]["masked_key"]

    # 3. Verify active
    resp = client.get("/api/providers")
    providers = resp.json()["providers"]
    my_p = next(p for p in providers if p["id"] == "my_claude")
    assert my_p["is_active"] is True

    # 4. DELETE /api/providers/my_claude
    del_resp = client.delete("/api/providers/my_claude")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"

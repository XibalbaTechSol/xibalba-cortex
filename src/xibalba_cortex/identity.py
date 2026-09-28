"""Process identity resolution for Cortex runtime boundaries."""

from __future__ import annotations

import os
from pathlib import Path

from integrity_sdk.did import DidFileError, read_did_file


def default_profile_root() -> Path:
    configured = os.environ.get("XIBALBA_CORTEX_HOME")
    if configured:
        return Path(configured).expanduser()
    hermes_home = os.environ.get("HERMES_HOME")
    if hermes_home:
        return Path(hermes_home).expanduser() / "xibalba-cortex"
    return Path.home() / ".hermes" / "xibalba-cortex"


def resolve_agent_id(*, profile_root: str | Path | None = None) -> str | None:
    """Use an explicit override, otherwise the validated public profile DID file."""
    override = str(os.environ.get("XIBALBA_AGENT_ID") or "").strip()
    if override:
        return override
    binding = read_did_file(
        Path(profile_root).expanduser() if profile_root is not None else default_profile_root()
    )
    if binding is None:
        return None
    value = str(binding.get("did") or "").strip()
    return value or None


def require_agent_id(*, profile_root: str | Path | None = None) -> str:
    value = resolve_agent_id(profile_root=profile_root)
    if not value:
        raise RuntimeError(
            "no Cortex agent identity is configured; provision agent.did.json or set "
            "XIBALBA_AGENT_ID as an explicit override"
        )
    return value


__all__ = ["DidFileError", "default_profile_root", "require_agent_id", "resolve_agent_id"]

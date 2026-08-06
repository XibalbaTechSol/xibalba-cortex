"""Codex launcher probe.

This module does not assume Codex's CLI surface in advance. It probes the live
environment for a launch command, version output, and likely hook surface so the
adapter can be treated as measured rather than imagined.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
import shutil
import subprocess
from typing import Any


@dataclass(slots=True)
class CodexProbeResult:
    executable: str | None
    version: str | None
    surface_kind: str
    hook_surface: str
    environment_signals: dict[str, str] = field(default_factory=dict)
    notes: str = ""

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


class CodexLauncherProbe:
    """Best-effort discovery of the Codex integration surface."""

    def __init__(self, executable_candidates: tuple[str, ...] = ("codex", "openai-codex")):
        self.executable_candidates = executable_candidates

    def discover(self) -> CodexProbeResult:
        environment_signals = {
            key: os.environ[key]
            for key in sorted(os.environ)
            if key.startswith("CODEX_") or key.startswith("OPENAI_") or key.startswith("AGENT_")
        }
        executable = next((candidate for candidate in self.executable_candidates if shutil.which(candidate)), None)
        if executable is None:
            return CodexProbeResult(
                executable=None,
                version=None,
                surface_kind="absent",
                hook_surface="unknown",
                environment_signals=environment_signals,
                notes="No Codex executable was found on PATH.",
            )

        version = self._version_for(executable)
        surface_kind = "cli"
        hook_surface = "unknown"
        notes = "Codex executable found; launcher surface must still be inspected for hook support."
        return CodexProbeResult(
            executable=executable,
            version=version,
            surface_kind=surface_kind,
            hook_surface=hook_surface,
            environment_signals=environment_signals,
            notes=notes,
        )

    def _version_for(self, executable: str) -> str | None:
        try:
            completed = subprocess.run(
                [executable, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        text = (completed.stdout or completed.stderr or "").strip()
        return text or None


__all__ = ["CodexLauncherProbe", "CodexProbeResult"]

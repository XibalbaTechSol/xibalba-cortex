"""Codex launcher probe.

This module does not assume Codex's CLI surface in advance. It probes the live
environment for a launch command, version output, and likely hook surface so the
adapter can be treated as measured rather than imagined.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Literal

from .runtime_bridge_contract import RuntimeEvent
from .runtime_controller import XibalbaRuntimeController


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


@dataclass(slots=True)
class CodexAdapter:
    """Lifecycle-only Codex adapter for callers that bind identity without spawning a process.

    Mirrors AgyWrapperShim's shape: session start/end plus best-effort observations. Unlike the
    Agy shim, it attaches CodexLauncherProbe's discovery result to provenance so callers can see
    what hook surface (if any) was detected, rather than silently assuming parity with Claude.
    """

    controller: XibalbaRuntimeController
    runtime: Literal["codex"] = "codex"
    provenance: dict[str, Any] = field(default_factory=dict)
    probe: CodexLauncherProbe = field(default_factory=CodexLauncherProbe)

    def start(
        self,
        *,
        session_id: str | None = None,
        traceparent: str | None = None,
        agent_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not session_id:
            return {"opened": False, "reason": "missing session_id"}
        discovered = self.probe.discover()
        opened = self.controller.open_session(
            self.runtime,
            session_id=session_id,
            traceparent=traceparent,
            agent_id=agent_id,
            provenance={**self.provenance, **kwargs, "hook_surface": discovered.hook_surface},
        )
        self.controller.ingest_event(
            RuntimeEvent(
                runtime=self.runtime,
                session_id=session_id,
                traceparent=traceparent,
                agent_id=agent_id,
                tool_name="codex.adapter.start",
                tool_outcome="success",
                provenance={**self.provenance, **kwargs},
                metadata={"hook": "start", "probe": discovered.to_record()},
            )
        )
        return {"opened": True, **opened}

    def end(
        self,
        *,
        session_id: str | None = None,
        summary: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not session_id:
            return {"closed": False, "reason": "missing session_id"}
        self.controller.ingest_event(
            RuntimeEvent(
                runtime=self.runtime,
                session_id=session_id,
                tool_name="codex.adapter.end",
                tool_outcome="success",
                provenance={**self.provenance, **kwargs},
                metadata={"hook": "end"},
            )
        )
        closed = self.controller.close_session(
            self.runtime,
            session_id=session_id,
            summary=summary,
            provenance={**self.provenance, **kwargs},
        )
        return {"closed": True, **closed}

    def record_observation(self, *, session_id: str | None = None, note: str | None = None, **kwargs: Any) -> dict[str, Any]:
        """Optional best-effort helper; not a native Codex tool hook."""
        if not session_id:
            return {"recorded": 0, "reason": "missing session_id"}
        if not note:
            return {"recorded": 0, "reason": "missing note"}
        self.controller.ingest_event(
            RuntimeEvent(
                runtime=self.runtime,
                session_id=session_id,
                tool_name="codex.adapter.observation",
                tool_outcome="unknown",
                provenance={**self.provenance, **kwargs},
                assistant_response=note,
                metadata={"hook": "observation"},
            )
        )
        return {"recorded": 1, "session_id": session_id}


class CodexLauncher:
    """Controller-aware Codex process launcher.

    This wrapper supplies identity/session context and records process-level telemetry.
    It does not claim Codex pre-tool or post-tool hook support.
    """

    def __init__(
        self,
        controller: XibalbaRuntimeController,
        *,
        executable_candidates: tuple[str, ...] = ("codex", "openai-codex"),
    ):
        self.controller = controller
        self.probe = CodexLauncherProbe(executable_candidates)

    def launch(
        self,
        *,
        session_id: str,
        args: list[str] | None = None,
        cwd: str | None = None,
        agent_id: str | None = None,
        traceparent: str | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        discovered = self.probe.discover()
        if discovered.executable is None:
            return {
                "launched": False,
                "reason": "codex executable not found",
                "probe": discovered.to_record(),
            }

        opened = self.controller.open_session(
            "codex",
            session_id=session_id,
            traceparent=traceparent,
            agent_id=agent_id,
            provenance={"source": "codex_launcher", "hook_surface": discovered.hook_surface},
        )
        command = [discovered.executable, *list(args or [])]
        launch_env = {
            **os.environ,
            **dict(env or {}),
            "XIBALBA_RUNTIME": "codex",
            "XIBALBA_SESSION_ID": session_id,
            "XIBALBA_GRAPH_HOOK_SURFACE": discovered.hook_surface,
        }
        if agent_id:
            launch_env["XIBALBA_AGENT_ID"] = agent_id
        if traceparent:
            launch_env["TRACEPARENT"] = traceparent

        try:
            completed = subprocess.run(
                command,
                cwd=str(Path(cwd)) if cwd else None,
                env=launch_env,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            outcome = "success" if completed.returncode == 0 else "error"
            result: dict[str, Any] = {
                "launched": True,
                "command": command,
                "cwd": cwd,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "opened": opened,
                "probe": discovered.to_record(),
            }
        except subprocess.TimeoutExpired as exc:
            outcome = "blocked"
            result = {
                "launched": False,
                "reason": "timeout",
                "command": command,
                "cwd": cwd,
                "timeout_seconds": timeout_seconds,
                "stdout": exc.stdout,
                "stderr": exc.stderr,
                "opened": opened,
                "probe": discovered.to_record(),
            }

        self.controller.ingest_event(
            RuntimeEvent(
                runtime="codex",
                session_id=session_id,
                traceparent=traceparent,
                agent_id=agent_id,
                tool_name="codex.launcher",
                tool_outcome=outcome,
                provenance={"source": "codex_launcher"},
                metadata={
                    "command": command,
                    "cwd": cwd,
                    "hook_surface": discovered.hook_surface,
                    "surface_kind": discovered.surface_kind,
                    "returncode": result.get("returncode"),
                    "reason": result.get("reason"),
                },
            )
        )
        self.controller.close_session(
            "codex",
            session_id=session_id,
            summary=f"Codex launcher exited with {outcome}.",
            provenance={"source": "codex_launcher", "outcome": outcome},
        )
        return result


__all__ = ["CodexAdapter", "CodexLauncher", "CodexLauncherProbe", "CodexProbeResult"]

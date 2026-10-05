"""Local-first Jev gateway for Cortex DecisionTrace annotations.

The gateway accepts only a redacted DecisionEnvelope, validates provider output, and turns
timeouts or malformed responses into an unavailable/rejected advisory. It never owns policy
authority, receipt signing, or anchoring.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import request

from integrity_sdk.core.decision_trace import (
    DecisionEnvelope,
    DecisionTraceError,
    FixtureJevProvider,
    JevAnalysis,
    JevProvider,
)


@dataclass(frozen=True)
class JevGateway:
    provider: JevProvider
    timeout_seconds: float = 1.0

    def analyze(self, event: DecisionEnvelope) -> JevAnalysis:
        try:
            analysis = self.provider.analyze(event)
            if not isinstance(analysis, JevAnalysis):
                raise DecisionTraceError("provider returned a non-JevAnalysis result")
            if analysis.status == "available" and analysis.observed_event_hash not in {None, event.event_hash}:
                raise DecisionTraceError("provider analysis is bound to a different event")
            return analysis
        except TimeoutError:
            return JevAnalysis(self.provider_id, "unavailable")
        except (DecisionTraceError, ValueError, TypeError):
            return JevAnalysis(self.provider_id, "rejected")
        except Exception:
            return JevAnalysis(self.provider_id, "unavailable")

    @property
    def provider_id(self) -> str:
        return str(getattr(self.provider, "provider_id", "jev.unknown"))


class HttpJevProvider:
    """Optional connector provider; local fixture remains the default.

    The payload is the already-redacted envelope body. The response must be a bounded JSON object
    with the advisory fields accepted by ``JevAnalysis``. No raw transcript is sent by this class.
    """

    provider_id = "jev.http.v1"

    def __init__(self, endpoint: str, *, timeout_seconds: float = 1.0, max_response_bytes: int = 32_768):
        self.endpoint = endpoint
        self.timeout_seconds = max(0.1, min(float(timeout_seconds), 10.0))
        self.max_response_bytes = max(1024, min(int(max_response_bytes), 256 * 1024))

    def analyze(self, event: DecisionEnvelope) -> JevAnalysis:
        payload = json.dumps(event.body(), separators=(",", ":")).encode("utf-8")
        req = request.Request(self.endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with request.urlopen(req, timeout=self.timeout_seconds) as response:  # noqa: S310 - configured operator endpoint
            raw = response.read(self.max_response_bytes + 1)
        if len(raw) > self.max_response_bytes:
            raise ValueError("Jev provider response exceeds configured bound")
        decoded = json.loads(raw.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("Jev provider response must be an object")
        return JevAnalysis(
            provider_id=self.provider_id,
            status=str(decoded.get("status", "available")),
            risk_category=decoded.get("risk_category"),
            transition_probabilities=decoded.get("transition_probabilities") or {},
            recommended_escalation=bool(decoded.get("recommended_escalation", False)),
            observed_event_hash=decoded.get("observed_event_hash") or event.event_hash,
            causal_claim=False,
        )


def local_jev_gateway() -> JevGateway:
    """Return the deterministic, offline provider used by local demos and tests."""
    return JevGateway(FixtureJevProvider())


__all__ = ["HttpJevProvider", "JevGateway", "local_jev_gateway"]

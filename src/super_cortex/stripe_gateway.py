"""Stripe's REST API gateway for Super-Cortex.

Fixed HTTPS origin, bounded requests, no card details stored in Super-Cortex.
Compatible with `integrity_sdk.billing.StripeGateway` and `ManagedConfig`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

STRIPE_API_ORIGIN = "https://api.stripe.com/v1"
DEFAULT_API_VERSION = "2025-06-30.basil"
REQUEST_TIMEOUT = (3.0, 10.0)
WEBHOOK_TOLERANCE_SECONDS = 300
_PLACEHOLDER_WORDS = ("dummy", "replace", "placeholder")

STRIPE_EVENTS_DDL = "CREATE TABLE IF NOT EXISTS stripe_events (id TEXT PRIMARY KEY, processed_at INTEGER NOT NULL)"


class BillingUnavailable(RuntimeError):
    """Billing cannot proceed: not configured, or Stripe failed. The message is safe to show."""


@dataclass(frozen=True)
class StripeConfig:
    secret_key: str = field(default="", repr=False)
    webhook_secret: str = field(default="", repr=False)
    live: bool = False
    api_version: str = DEFAULT_API_VERSION

    @property
    def billing_ready(self) -> bool:
        """True only for a real key of the configured mode and a real webhook secret."""
        key_prefix = "sk_live_" if self.live else "sk_test_"
        lowered = self.secret_key.lower()
        return bool(
            self.secret_key.startswith(key_prefix)
            and not any(word in lowered for word in _PLACEHOLDER_WORDS)
            and self.webhook_secret.startswith("whsec_")
            and not any(word in self.webhook_secret.lower() for word in _PLACEHOLDER_WORDS)
        )


def _send(method: str, url: str, **kwargs: Any) -> Any:
    """The one network call to Stripe API. Separate so tests can monkeypatch it."""
    import httpx

    auth = kwargs.get("auth")
    data = kwargs.get("data")
    headers = kwargs.get("headers") or {}
    timeout_tuple = kwargs.get("timeout", REQUEST_TIMEOUT)
    timeout = httpx.Timeout(timeout_tuple[1], connect=timeout_tuple[0]) if isinstance(timeout_tuple, tuple) else 10.0

    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.request(method, url, auth=auth, data=data, headers=headers)
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        # Stripe errors may include customer/provider data; never forward raw responses.
        raise BillingUnavailable("Stripe is temporarily unavailable; retry shortly") from exc


def ensure_stripe_events_table(conn: Any) -> None:
    conn.execute(STRIPE_EVENTS_DDL)


def record_once(conn: Any, event_id: str, *, processed_at: int) -> bool:
    """Claim webhook `event_id`. True the first time, False on redelivery."""
    if not isinstance(event_id, str) or not event_id.startswith("evt_"):
        raise ValueError("Stripe event ids start with evt_")
    cursor = conn.execute(
        "INSERT OR IGNORE INTO stripe_events (id, processed_at) VALUES (?, ?)",
        (event_id, int(processed_at)),
    )
    return cursor.rowcount == 1


class StripeGateway:
    """Product gateway compatible with `integrity_sdk.billing.StripeGateway` and `ManagedConfig`."""

    def __init__(self, config: Any):
        self.managed_config = config if not isinstance(config, StripeConfig) else None
        if isinstance(config, StripeConfig):
            self.config = config
        else:
            is_ready = getattr(config, "billing_ready", True)
            secret = getattr(config, "stripe_secret_key", "") if is_ready else ""
            self.config = StripeConfig(
                secret_key=secret,
                webhook_secret=getattr(config, "stripe_webhook_secret", ""),
                live=getattr(config, "stripe_live", False),
                api_version=getattr(config, "stripe_api_version", DEFAULT_API_VERSION),
            )

    def request(
        self,
        method: str,
        path: str,
        *,
        data: Optional[Mapping[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        if not self.config.billing_ready:
            raise BillingUnavailable("Stripe billing is not configured; placeholder keys cannot be used")
        if not path.startswith("/") or ".." in path or "?" in path or "#" in path or "//" in path:
            raise ValueError("invalid Stripe resource path")
        headers: dict[str, str] = {"Stripe-Version": self.config.api_version}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        result = _send(
            method,
            STRIPE_API_ORIGIN + path,
            auth=(self.config.secret_key, ""),
            data=dict(data) if data is not None else None,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )
        if not isinstance(result, dict):
            raise BillingUnavailable("Stripe returned an invalid response")
        return result

    def send_meter_event(
        self,
        event_name: str,
        customer_id: str,
        value: int,
        identifier: str,
        timestamp: Optional[int] = None,
    ) -> dict:
        if not event_name or not customer_id.startswith("cus_") or not identifier:
            raise ValueError("meter event needs an event name, a cus_ customer id and an identifier")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("meter event value must be a positive integer")
        data: dict[str, str] = {
            "event_name": event_name,
            "payload[stripe_customer_id]": customer_id,
            "payload[value]": str(value),
            "identifier": identifier,
        }
        if timestamp is not None:
            data["timestamp"] = str(int(timestamp))
        return self.request("POST", "/billing/meter_events", data=data, idempotency_key=identifier)

    def verify_event(self, body: bytes, signature: str, *, now: Optional[float] = None) -> dict:
        """Verify a webhook's `Stripe-Signature` header and return the parsed event."""
        if not self.config.billing_ready:
            raise BillingUnavailable("Stripe webhooks are not configured")
        fields = [part.split("=", 1) for part in signature.split(",") if "=" in part]
        timestamps = [v for k, v in fields if k == "t"]
        signatures = [v for k, v in fields if k == "v1"]
        try:
            if len(timestamps) != 1:
                raise ValueError()
            timestamp = int(timestamps[0])
            if abs((time.time() if now is None else now) - timestamp) > WEBHOOK_TOLERANCE_SECONDS:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("invalid or expired Stripe signature") from None
        expected = hmac.new(
            self.config.webhook_secret.encode(),
            str(timestamp).encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
            raise ValueError("invalid Stripe signature")
        try:
            event = json.loads(body)
            if (
                not isinstance(event, dict)
                or not isinstance(event.get("id"), str)
                or not isinstance(event.get("data", {}).get("object"), dict)
            ):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValueError("invalid Stripe event") from None
        if event.get("livemode") is not self.config.live:
            raise ValueError("Stripe event mode does not match deployment")
        return event


__all__ = [
    "BillingUnavailable",
    "StripeConfig",
    "StripeGateway",
    "ensure_stripe_events_table",
    "record_once",
]

"""Stripe's REST API. Fixed HTTPS origin, bounded requests, no card details in Cortex."""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import requests

from .config import ManagedConfig


class BillingUnavailable(RuntimeError):
    pass


class StripeGateway:
    def __init__(self, config: ManagedConfig):
        self.config = config

    def request(self, method: str, path: str, *, data=None, idempotency_key=None) -> dict:
        if not self.config.billing_ready:
            raise BillingUnavailable("Stripe billing is not configured; placeholder keys cannot create a checkout")
        if not path.startswith("/") or ".." in path or "?" in path:
            raise ValueError("invalid Stripe resource path")
        headers = {"Stripe-Version": self.config.stripe_api_version}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = requests.request(method, "https://api.stripe.com/v1" + path,
                auth=(self.config.stripe_secret_key, ""), data=data, headers=headers,
                timeout=(3, 10), allow_redirects=False)
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError) as exc:
            # Stripe errors may include customer/provider data; do not forward raw responses.
            raise BillingUnavailable("Stripe is temporarily unavailable; retry shortly") from exc
        if not isinstance(result, dict):
            raise BillingUnavailable("Stripe returned an invalid response")
        return result

    def verify_event(self, body: bytes, signature: str, *, now: float | None = None) -> dict:
        if not self.config.billing_ready:
            raise BillingUnavailable("Stripe webhooks are not configured")
        fields = [part.split("=", 1) for part in signature.split(",") if "=" in part]
        timestamps = [v for k, v in fields if k == "t"]
        signatures = [v for k, v in fields if k == "v1"]
        try:
            if len(timestamps) != 1:
                raise ValueError()
            timestamp = int(timestamps[0])
            if abs((time.time() if now is None else now) - timestamp) > 300:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("invalid or expired Stripe signature") from None
        expected = hmac.new(self.config.stripe_webhook_secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
            raise ValueError("invalid Stripe signature")
        try:
            event = json.loads(body)
            if not isinstance(event, dict) or not isinstance(event.get("id"), str) or not isinstance(event.get("data", {}).get("object"), dict):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValueError("invalid Stripe event") from None
        if event.get("livemode") is not self.config.stripe_live:
            raise ValueError("Stripe event mode does not match deployment")
        return event

"""Stripe's REST API. Fixed HTTPS origin, bounded requests, no card details in Cortex.

Powered by `integrity_sdk.billing.StripeGateway`.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from integrity_sdk.billing import (
    BillingUnavailable,
    StripeConfig,
    StripeGateway as _SdkStripeGateway,
)

from .config import ManagedConfig

__all__ = ["BillingUnavailable", "StripeConfig", "StripeGateway"]


class StripeGateway(_SdkStripeGateway):
    """Product gateway extending integrity_sdk.billing.StripeGateway with ManagedConfig support."""

    def __init__(self, config: ManagedConfig | StripeConfig):
        self.managed_config = config if isinstance(config, ManagedConfig) else None
        if isinstance(config, StripeConfig):
            stripe_config = config
        else:
            # ManagedConfig: if not billing_ready (e.g. placeholder keys or missing prices),
            # clear the secret key so StripeConfig also fails closed.
            is_ready = getattr(config, "billing_ready", True)
            secret = getattr(config, "stripe_secret_key", "") if is_ready else ""
            stripe_config = StripeConfig(
                secret_key=secret,
                webhook_secret=getattr(config, "stripe_webhook_secret", ""),
                live=getattr(config, "stripe_live", False),
                api_version=getattr(config, "stripe_api_version", "2025-06-30.basil"),
            )
        super().__init__(stripe_config)

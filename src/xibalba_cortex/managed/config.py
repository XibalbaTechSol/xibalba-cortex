from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ManagedConfig:
    home: Path
    public_url: str = "http://localhost:8430"
    stripe_secret_key: str = field(default="", repr=False)
    stripe_webhook_secret: str = field(default="", repr=False)
    pro_price_id: str = ""
    team_price_id: str = ""
    stripe_live: bool = False
    allow_signup: bool = False
    signup_daily_limit: int = 20
    max_body_bytes: int = 65_536
    max_content_bytes: int = 16_384
    # A pinned, supported version; upgrades must be tested alongside webhook fixtures.
    stripe_api_version: str = "2025-06-30.basil"

    def __post_init__(self):
        object.__setattr__(self, "home", Path(self.home).expanduser().resolve())
        parts = urlsplit(self.public_url)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path not in {"", "/"}:
            raise ValueError("public_url must be an origin without credentials, path, query or fragment")
        if parts.scheme != "https" and parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("public_url requires HTTPS outside loopback development")
        if min(self.signup_daily_limit, self.max_body_bytes, self.max_content_bytes) < 1:
            raise ValueError("managed resource limits must be positive")
        if self.pro_price_id and self.pro_price_id == self.team_price_id:
            raise ValueError("paid plans must have distinct Stripe prices")

    @property
    def billing_ready(self) -> bool:
        key_prefix = "sk_live_" if self.stripe_live else "sk_test_"
        return bool(self.stripe_secret_key.startswith(key_prefix) and not any(word in self.stripe_secret_key.lower() for word in ("dummy", "replace", "placeholder")) and self.stripe_webhook_secret.startswith("whsec_") and self.pro_price_id.startswith("price_") and self.team_price_id.startswith("price_"))

    def pilot_readiness(self) -> dict[str, object]:
        """Return the gates that must be closed before enabling a hosted pilot.

        This is deliberately stricter than liveness. A local development service with
        dummy Stripe keys remains healthy while reporting why it cannot accept customers.
        """
        parts = urlsplit(self.public_url)
        public_origin = parts.scheme == "https" and parts.hostname not in {"localhost", "127.0.0.1", "::1"}
        smtp_ready = bool(os.environ.get("CORTEX_SMTP_HOST", "").strip() and os.environ.get("CORTEX_SMTP_FROM", "").strip())
        storage_ready = self.home.is_dir() and os.access(self.home, os.W_OK)
        checks = {
            "public_origin": {"ready": public_origin, "detail": "HTTPS public origin is configured" if public_origin else "Set CORTEX_MANAGED_PUBLIC_URL to the selected HTTPS domain"},
            "stripe_sandbox": {"ready": self.billing_ready and not self.stripe_live, "detail": "Stripe test mode and approved monthly prices are configured" if self.billing_ready and not self.stripe_live else "Configure real sk_test_, whsec_, Pro and Team Price IDs"},
            "smtp_delivery": {"ready": smtp_ready, "detail": "SMTP host and sender are configured" if smtp_ready else "Set CORTEX_SMTP_HOST and CORTEX_SMTP_FROM"},
            "registration": {"ready": self.allow_signup, "detail": "Verified signup is enabled" if self.allow_signup else "Set CORTEX_MANAGED_ALLOW_SIGNUP=true after delivery testing"},
            "persistent_storage": {"ready": storage_ready, "detail": "Managed data home is writable" if storage_ready else "Managed data home is not writable"},
        }
        return {"schema_version": "xibalba.managed_pilot_readiness.v1", "ready": all(item["ready"] for item in checks.values()), "checks": checks, "disclaimer": "Pilot gate status only; this does not establish SLA, HA, backup or compliance evidence."}

    @classmethod
    def from_env(cls) -> ManagedConfig:
        return cls(
            home=Path(os.environ.get("CORTEX_MANAGED_HOME", "/data/cortex-managed")),
            public_url=os.environ.get("CORTEX_MANAGED_PUBLIC_URL", "http://localhost:8430").rstrip("/"),
            stripe_secret_key=os.environ.get("STRIPE_SECRET_KEY", ""),
            stripe_webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
            pro_price_id=os.environ.get("STRIPE_PRO_MONTHLY_PRICE_ID", ""),
            team_price_id=os.environ.get("STRIPE_TEAM_MONTHLY_PRICE_ID", ""),
            stripe_live=os.environ.get("CORTEX_STRIPE_LIVE", "false").lower() == "true",
            allow_signup=os.environ.get("CORTEX_MANAGED_ALLOW_SIGNUP", "false").lower() == "true",
            signup_daily_limit=int(os.environ.get("CORTEX_MANAGED_SIGNUP_DAILY_LIMIT", "20")),
        )

"""Small server-only Supabase PostgREST adapter for the managed control plane."""
from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import requests


class SupabaseAdapter:
    def __init__(self, url: str, service_role_key: str, *, timeout: float = 10.0):
        self.url = url.rstrip("/") + "/"
        self.service_role_key = service_role_key
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.url.strip("/") and self.service_role_key.strip())

    def _request(self, method: str, table: str, *, payload: dict[str, Any] | None = None, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
        if not table.startswith("cortex_"):
            raise ValueError("invalid Cortex control-plane table")
        response = requests.request(method, urljoin(self.url, "rest/v1/" + table), json=payload,
            params=params, headers={"apikey": self.service_role_key, "Authorization": "Bearer " + self.service_role_key, "Content-Type": "application/json", "Prefer": "return=representation"}, timeout=self.timeout)
        if not response.ok:
            raise RuntimeError("Supabase control-plane request failed")
        if not response.content:
            return []
        data = response.json()
        return data if isinstance(data, list) else []

    def probe(self) -> bool:
        try:
            self._request("GET", "cortex_tenants", params={"select": "id", "limit": "1"})
        except (OSError, requests.RequestException, RuntimeError, ValueError):
            return False
        return True

    def mirror_tenant(self, tenant: dict[str, Any]) -> None:
        self._request("POST", "cortex_tenants", payload={k: tenant[k] for k in ("id", "owner_account_id", "plan", "status", "customer_id", "subscription_id", "period_end", "cancel_at_period_end") if k in tenant})

    def mirror_usage(self, tenant_id: str, month: str, meter: str, amount: int) -> None:
        self._request("POST", "cortex_usage", payload={"tenant_id": tenant_id, "month": month + "-01", "meter": meter, "amount": amount})

"""Supabase Auth access-token verification and stable subject resolution."""
from __future__ import annotations

import jwt


class SupabaseAuthVerifier:
    def __init__(self, project_url: str, *, audience: str = "authenticated", jwks_client=None):
        url = project_url.rstrip("/")
        if not url.startswith("https://") and not url.startswith("http://127.0.0.1") and not url.startswith("http://localhost"):
            raise ValueError("Supabase project URL must use HTTPS outside loopback")
        self.issuer = url + "/auth/v1"
        self.audience = audience
        self.jwks = jwks_client or jwt.PyJWKClient(self.issuer + "/.well-known/jwks.json", timeout=5)

    def verify(self, token: str) -> dict:
        if not token or len(token) > 16384:
            raise ValueError("invalid Supabase access token")
        key = self.jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["ES256", "RS256"], issuer=self.issuer,
                            audience=self.audience,
                            options={"require": ["exp", "iat", "sub", "iss", "aud"]})
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise ValueError("Supabase token subject is missing")
        if claims.get("role") not in {None, "authenticated"}:
            raise ValueError("Supabase token role is not authenticated")
        return claims

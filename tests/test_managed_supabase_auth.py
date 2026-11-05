import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from xibalba_cortex.managed.supabase_auth import SupabaseAuthVerifier


def test_supabase_auth_verifies_signature_issuer_audience_and_expiry():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = SupabaseAuthVerifier("https://project.supabase.co")

    class Keys:
        def get_signing_key_from_jwt(self, token):
            return type("SigningKey", (), {"key": private.public_key()})()

    verifier.jwks = Keys()
    now = int(time.time())
    good = {"iss": verifier.issuer, "aud": "authenticated", "sub": str(uuid.uuid4()),
            "role": "authenticated", "iat": now, "exp": now + 60}
    encode = lambda claims, key=private: jwt.encode(claims, key, algorithm="RS256")
    assert verifier.verify(encode(good))["sub"] == good["sub"]
    for bad in (good | {"iss": "https://attacker.test"},
                good | {"aud": "other"}, good | {"exp": now - 1},
                good | {"role": "service_role"}, good | {"role": None},
                good | {"sub": "not-a-uuid"}):
        with pytest.raises(jwt.PyJWTError) if bad.get("role") == "authenticated" and bad.get("sub") != "not-a-uuid" else pytest.raises(ValueError):
            verifier.verify(encode(bad))
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(jwt.PyJWTError):
        verifier.verify(encode(good, attacker))


@pytest.mark.parametrize("url", [
    "http://localhost.example.com",
    "http://127.0.0.1.example.com",
    "http://example.com",
    "https://project.supabase.co/path",
    "https://user:pass@project.supabase.co",
])
def test_supabase_auth_rejects_non_loopback_http_and_non_origin_urls(url):
    with pytest.raises(ValueError):
        SupabaseAuthVerifier(url)


@pytest.mark.parametrize("url", [
    "http://localhost:54321",
    "http://127.0.0.1:54321",
    "http://[::1]:54321",
    "https://project.supabase.co",
])
def test_supabase_auth_accepts_secure_or_loopback_origins(url):
    verifier = SupabaseAuthVerifier(url, jwks_client=object())
    assert verifier.issuer == url.rstrip("/") + "/auth/v1"

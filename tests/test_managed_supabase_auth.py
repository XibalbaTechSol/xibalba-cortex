import time

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
    good = {"iss": verifier.issuer, "aud": "authenticated", "sub": "auth-user-1",
            "role": "authenticated", "iat": now, "exp": now + 60}
    encode = lambda claims, key=private: jwt.encode(claims, key, algorithm="RS256")
    assert verifier.verify(encode(good))["sub"] == "auth-user-1"
    for bad in (good | {"iss": "https://attacker.test"},
                good | {"aud": "other"}, good | {"exp": now - 1},
                good | {"role": "service_role"}):
        with pytest.raises(jwt.PyJWTError) if bad.get("role") != "service_role" else pytest.raises(ValueError):
            verifier.verify(encode(bad))
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(jwt.PyJWTError):
        verifier.verify(encode(good, attacker))

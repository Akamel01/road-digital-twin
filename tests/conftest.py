import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from twin import fixtures
from twin.access import AccessVerifier


@pytest.fixture
def plane_points():
    return fixtures.make_plane(seed=0)


@pytest.fixture
def canopy_points():
    return fixtures.make_canopy(seed=1)


@pytest.fixture
def wall_points():
    return fixtures.make_wall(seed=2)


@pytest.fixture
def scene_points():
    return fixtures.make_scene(seed=0)


ACCESS_TEAM = "papyrus"
ACCESS_AUD = "test-aud"
OPERATOR_EMAIL = "operator@example.com"
ACCESS_ISSUER = f"https://{ACCESS_TEAM}.cloudflareaccess.com"


class _FakeKeys:
    """Stands in for PyJWKClient: returns the test team key for any token."""

    def __init__(self, key):
        self.key = key

    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=self.key)


@pytest.fixture(scope="session")
def access():
    """Test Access verifier (synthetic team key) and a token maker. Never a real key."""
    team = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def make_token(
        key=team,
        aud=ACCESS_AUD,
        email=OPERATOR_EMAIL,
        exp_in=300,
        iss=ACCESS_ISSUER,
        alg="RS256",
    ):
        now = int(time.time())
        claims = {
            "iss": iss,
            "aud": aud,
            "email": email,
            "iat": now,
            "exp": now + exp_in,
        }
        if alg == "HS256":
            return jwt.encode(
                claims, "not-the-team-key-0123456789abcdef-x", algorithm="HS256"
            )
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})

    verifier = AccessVerifier(
        ACCESS_TEAM, ACCESS_AUD, OPERATOR_EMAIL, keys=_FakeKeys(team.public_key())
    )
    return SimpleNamespace(verifier=verifier, token=make_token, forged=forged)

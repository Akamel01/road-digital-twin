"""Cloudflare Access check for the write routes (/api/w/*).

Source of truth: docs/design/twin-v1-spec.md, sections 3 and 8; docs/research/cloudflare-access.md.
Access signs each request in the Cf-Access-Jwt-Assertion header (RS256, team keys at
/cdn-cgi/access/certs). This module checks that header against the team's keys, the
application audience, the issuer, the expiry, and the operator's email.
"""

import os
from typing import Any, Protocol

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient

HEADER = "Cf-Access-Jwt-Assertion"
ALGORITHMS = ["RS256"]  # never HS256: the team key is public, so it must not be an HMAC secret


class Verifier(Protocol):
    def verify(self, request: Request) -> str:
        """Return the operator's email, or raise HTTPException (401 or 403)."""


class AccessVerifier:
    def __init__(
        self,
        team: str,
        aud: str,
        operator_email: str,
        keys: Any = None,
    ) -> None:
        self.issuer = f"https://{team}.cloudflareaccess.com"
        self.aud = aud
        self.operator_email = operator_email.lower()
        # keys: anything with get_signing_key_from_jwt(token).key, e.g. a test double.
        self.keys = keys or PyJWKClient(
            f"{self.issuer}/cdn-cgi/access/certs", cache_keys=True
        )

    def verify(self, request: Request) -> str:
        token = request.headers.get(HEADER)
        if not token:
            raise HTTPException(401, f"missing {HEADER}")
        try:
            key = self.keys.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=ALGORITHMS,
                audience=self.aud,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:  # bad signature, alg, aud, iss, expiry, unknown key
            raise HTTPException(401, "invalid access token") from exc
        email = str(claims.get("email", "")).lower()
        if email != self.operator_email:
            raise HTTPException(403, "not the operator")
        return email


class DevNoAuth:
    """TWIN_DEV_NO_AUTH=1 on a local machine only. Tests must not use it."""

    def verify(self, request: Request) -> str:
        return "dev"


def verifier_from_env() -> Verifier:
    """Build the verifier from the environment. Refuses to start without the settings."""
    if os.environ.get("TWIN_DEV_NO_AUTH") == "1":
        return DevNoAuth()
    aud = os.environ.get("TWIN_ACCESS_AUD")
    email = os.environ.get("TWIN_OPERATOR_EMAIL")
    if not aud or not email:
        raise RuntimeError(
            "write routes need TWIN_ACCESS_AUD and TWIN_OPERATOR_EMAIL "
            "(TWIN_DEV_NO_AUTH=1 for local development only)"
        )
    return AccessVerifier(os.environ.get("TWIN_ACCESS_TEAM") or "papyrus", aud, email)

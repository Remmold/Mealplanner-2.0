"""Supabase JWT verification + per-request user context.

Supports both:
  * Asymmetric signing (ES256/RS256) — the modern Supabase default for new
    projects. Public keys are fetched from the project's JWKS endpoint.
  * Symmetric signing (HS256) — the legacy "JWT Secret" path. Falls back to
    SUPABASE_JWT_SECRET when present.

We peek at the JWT header (unverified) to pick the right path per request,
then verify with the correct key and algorithm set.

Usage:
    @router.get("/something")
    async def handler(user: CurrentUser = Depends(get_current_user)):
        ...
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
SUPABASE_JWT_AUDIENCE = "authenticated"

# Asymmetric algorithms Supabase may sign with. HS256 stays in the legacy
# branch (different verification key entirely).
_ASYMMETRIC_ALGS = ("RS256", "ES256")


@dataclass
class CurrentUser:
    user_id: str          # UUID string from JWT 'sub'
    email: Optional[str]
    raw_token: str        # original JWT (passed to Postgres via SET LOCAL)
    claims: dict          # decoded JWT payload


_bearer = HTTPBearer(auto_error=False)
_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    """Lazy-init the JWKS client. Caches keys with a 1-hour lifespan so we
    don't hit Supabase on every request."""
    global _jwks_client
    if _jwks_client is None:
        if not SUPABASE_URL:
            raise HTTPException(status_code=500, detail="SUPABASE_URL not configured")
        _jwks_client = PyJWKClient(
            f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json",
            cache_keys=True,
            lifespan=3600,
        )
    return _jwks_client


def _decode(token: str) -> dict:
    # Inspect the header (unverified) to choose between asymmetric and symmetric paths.
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Malformed token: {e}")

    alg = str(header.get("alg", ""))

    try:
        if alg in _ASYMMETRIC_ALGS:
            signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=list(_ASYMMETRIC_ALGS),
                audience=SUPABASE_JWT_AUDIENCE,
            )
        elif alg.startswith("HS"):
            if not SUPABASE_JWT_SECRET:
                raise HTTPException(
                    status_code=500,
                    detail="SUPABASE_JWT_SECRET required for HS-signed tokens",
                )
            return jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience=SUPABASE_JWT_AUDIENCE,
            )
        else:
            raise HTTPException(status_code=401, detail=f"Unsupported JWT algorithm: {alg}")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidAudienceError:
        raise HTTPException(status_code=401, detail="Token audience mismatch")
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> CurrentUser:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = creds.credentials
    claims = _decode(token)

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing sub claim")

    return CurrentUser(
        user_id=user_id,
        email=claims.get("email"),
        raw_token=token,
        claims=claims,
    )


async def get_optional_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[CurrentUser]:
    """Same as get_current_user but returns None for unauthenticated requests
    instead of raising. Use for endpoints that work both ways."""
    if creds is None or creds.scheme.lower() != "bearer":
        return None
    try:
        claims = _decode(creds.credentials)
    except HTTPException:
        return None
    user_id = claims.get("sub")
    if not user_id:
        return None
    return CurrentUser(
        user_id=user_id,
        email=claims.get("email"),
        raw_token=creds.credentials,
        claims=claims,
    )

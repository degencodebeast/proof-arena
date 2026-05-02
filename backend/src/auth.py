"""Authentication dependencies — API key auth for V1.

V1 auth model (PLACEHOLDER — not production-grade):
- get_current_user: accepts any non-empty bearer token and derives a
  bounded stable identity from it. Identity rule (Task 41 fixpack):
  if the bearer is JWT-shaped and carries a usable `sub` claim that
  fits within 128 chars, use the `sub` directly. Otherwise fall back
  to a deterministic SHA-256 hash of the raw bearer prefixed with
  `bearer_sha256:`. The result is ALWAYS ≤ 128 chars so it fits the
  ``agents.privy_user_id`` and ``agent_instances.instance_owner_ref``
  ``varchar(128)`` columns. Anti-spam still works per stable identity.
  Full Privy JWT verification is deferred to Task 15.
- require_admin: validates ADMIN_API_KEY. Accepts both
  ``Authorization: Bearer <ADMIN_API_KEY>`` and ``X-Admin-Key`` header
  forms (Task 41 fixpack F4). Non-admin keys return 403.
- wallet_address: always None in V1. Privy embedded wallet flow will
  supply real wallet identity when wired in Task 12/15.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config import settings

security = HTTPBearer(auto_error=False)


# Task 41 F1 — DB column width for both privy_user_id (agents) and
# instance_owner_ref (agent_instances). Identity derivation guarantees
# the returned string is ≤ this width.
_MAX_IDENTITY_CHARS = 128
_HASH_PREFIX = "bearer_sha256:"  # 14 chars; + 64 hex = 78 total


@dataclass
class PrivyUser:
    """Authenticated user."""

    privy_user_id: str
    wallet_address: str | None = None


def _b64url_decode_padded(value: str) -> bytes:
    """Decode a base64url segment, restoring missing `=` padding."""
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _try_extract_jwt_sub(token: str) -> str | None:
    """If the token is JWT-shaped and carries a usable `sub` claim that
    fits the identity width, return it. Otherwise return None.

    Does NOT verify the JWT signature (Task 15 will add real Privy
    verification). Only used to extract a stable user id for V1
    identity tracking.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload_bytes = _b64url_decode_padded(parts[1])
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    sub = payload.get("sub") if isinstance(payload, dict) else None
    if not isinstance(sub, str) or not sub:
        return None
    if len(sub) > _MAX_IDENTITY_CHARS:
        return None
    return sub


def _derive_identity(token: str) -> str:
    """Derive a bounded stable identity from a bearer token.

    Returns a string ≤ 128 chars. Either the JWT `sub` claim (if
    JWT-shaped, valid JSON, and fits) or `bearer_sha256:<hex>`.
    """
    sub = _try_extract_jwt_sub(token)
    if sub is not None:
        return sub
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{_HASH_PREFIX}{digest}"


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> PrivyUser:
    """Validate bearer token. Returns authenticated user with bounded id.

    V1 placeholder (Task 41 fixpack F1): accepts any non-empty bearer.
    Identity is derived to fit the 128-char DB column — never the raw
    bearer. Full Privy JWT validation deferred to Task 15.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )
    token = credentials.credentials
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty bearer token",
        )
    identity = _derive_identity(token)
    return PrivyUser(privy_user_id=identity, wallet_address=None)


async def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> PrivyUser:
    """Require the caller to be the platform admin.

    Accepts the admin key via either:
    - ``Authorization: Bearer <ADMIN_API_KEY>``, or
    - ``X-Admin-Key: <ADMIN_API_KEY>`` (Task 41 fixpack F4).

    Either-or: present + correct in either header → admin. Missing
    both → 401. Present but wrong in both → 403.
    """
    bearer_token = credentials.credentials if credentials is not None else None
    if not bearer_token and not x_admin_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )
    if not settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API key not configured",
        )
    if (
        bearer_token != settings.ADMIN_API_KEY
        and x_admin_key != settings.ADMIN_API_KEY
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized as admin",
        )
    return PrivyUser(privy_user_id="admin", wallet_address=None)

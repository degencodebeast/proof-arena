"""Authentication dependencies — API key auth for V1.

V1 auth model (PLACEHOLDER — not production-grade):
- get_current_user: accepts any non-empty bearer token. The token
  becomes the privy_user_id. Anti-spam is per-token, NOT per-real-user.
  A caller can rotate tokens to bypass submission limits.
  Full Privy JWT verification is deferred to Task 15.
- require_admin: validates ADMIN_API_KEY. Non-admin tokens return 403.
- wallet_address: always None in V1. Privy embedded wallet flow will
  supply real wallet identity when wired in Task 12/15.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config import settings

security = HTTPBearer(auto_error=False)


@dataclass
class PrivyUser:
    """Authenticated user."""

    privy_user_id: str
    wallet_address: str | None = None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> PrivyUser:
    """Validate bearer token. Returns authenticated user.

    V1: accepts any non-empty bearer token as a valid API key.
    The token becomes the privy_user_id for identity tracking.
    Full Privy JWT validation deferred to Task 15.
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
    # V1: token IS the user identity
    return PrivyUser(privy_user_id=token, wallet_address=None)


async def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> PrivyUser:
    """Require the caller to be the platform admin.

    Validates against ADMIN_API_KEY. Non-admin tokens return 403.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )
    token = credentials.credentials
    if not settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API key not configured",
        )
    if token != settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized as admin",
        )
    return PrivyUser(privy_user_id="admin", wallet_address=None)

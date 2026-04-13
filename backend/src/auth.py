"""Authentication dependencies — Privy JWT validation.

Structurally correct stubs for Task 11 to extend with real
Privy token validation. The admin check uses a simple pubkey
comparison against the configured authority.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config import settings

security = HTTPBearer(auto_error=False)


@dataclass
class PrivyUser:
    """Authenticated user from Privy JWT."""

    privy_user_id: str
    wallet_address: str | None = None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> PrivyUser:
    """Validate Privy JWT and return the authenticated user.

    TODO (Task 11): Implement real Privy JWT verification.
    For now, returns a stub user for development.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )
    # Stub: In production, decode and verify the Privy JWT here.
    # Extract privy_user_id and wallet_address from claims.
    return PrivyUser(
        privy_user_id="stub-user",
        wallet_address=None,
    )


async def require_admin(
    user: PrivyUser = Depends(get_current_user),
) -> PrivyUser:
    """Require the caller to be the platform admin.

    The admin is identified by checking against a configured list
    or by verifying the Privy user_id matches the authority.
    """
    # Stub: In production, check user against admin allowlist.
    # For V1, the backend itself is the admin — this dependency
    # gates the API endpoints, not the on-chain authority.
    return user

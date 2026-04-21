"""Chain package — program-client factory.

`get_program_client()` is the single place that decides whether a real
`AgentArenaClient` can be constructed from current settings. It is
fail-closed: any missing or invalid configuration returns None (never a
partially-configured client). Callers that need on-chain state transitions
must raise `OnchainError` when this returns None; admin endpoints surface
that as HTTP 502.

Why fail-closed here instead of at the call site:
    The admin POST /challenges and settlement paths already call
    _require_program() to raise OnchainError. Centralizing configuration
    validation in the factory guarantees "no on-chain client" is the only
    failure mode the rest of the backend has to handle — we do not want
    partial Privy/anchorpy state leaking into services.

Inputs considered:
    - settings.PROGRAM_ID must be non-empty.
    - settings.AUTHORITY_KEYPAIR_PATH must be non-empty AND point at a
      readable file AND decode into a 64-byte Solana keypair.
    - SolanaService.is_ready covers the last two.

Failure taxonomy this catches:
    - empty PROGRAM_ID                            → None + warn
    - empty AUTHORITY_KEYPAIR_PATH                → None + warn
    - keypair file missing                        → is_ready=False → None + warn
    - keypair file contains invalid JSON          → None + warn (SolanaService
                                                    ctor raises; caught here)
    - keypair bytes are not 64-byte Solana secret → None + warn
    - anchorpy IDL / Program construction error   → None + warn
"""

from __future__ import annotations

import logging

from src.chain.program_client import AgentArenaClient
from src.config import settings
from src.services.solana_service import SolanaService

logger = logging.getLogger(__name__)


def get_program_client() -> AgentArenaClient | None:
    """Return a live AgentArenaClient, or None if not configured.

    This function never raises. Any failure path logs a warning and returns
    None. Callers that need on-chain state must fail closed against None.
    """
    if not settings.PROGRAM_ID:
        logger.warning("PROGRAM_ID not configured; program client unavailable.")
        return None
    if not settings.AUTHORITY_KEYPAIR_PATH:
        logger.warning(
            "AUTHORITY_KEYPAIR_PATH not configured; program client unavailable."
        )
        return None

    # Constructing SolanaService can raise if the keypair file exists but is
    # malformed JSON or wrong-length bytes. Treat those as misconfiguration,
    # not as crash paths.
    try:
        solana = SolanaService()
    except Exception as exc:
        logger.warning(
            "SolanaService failed to initialize from AUTHORITY_KEYPAIR_PATH=%s: %s",
            settings.AUTHORITY_KEYPAIR_PATH,
            exc,
        )
        return None

    if not solana.is_ready:
        logger.warning(
            "SolanaService not ready (authority keypair missing or unloadable); "
            "program client unavailable."
        )
        return None

    try:
        return AgentArenaClient(solana.provider)
    except Exception as exc:  # IDL load, program_id parse, etc.
        logger.warning("Failed to construct AgentArenaClient: %s", exc)
        return None


__all__ = ["get_program_client"]

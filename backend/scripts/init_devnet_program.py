#!/usr/bin/env python
"""init_devnet_program.py — idempotent on-chain initialize() for Agent Arena.

Purpose
-------
Submit the Anchor program's `initialize` instruction against the deployed
devnet program at PROGRAM_ID. Safe to run repeatedly: on the second+ run,
the program returns an "already initialized" / "account already in use"
error; we catch that and exit 0 instead of failing.

Hard guards
-----------
- **Devnet-only**: exits non-zero if SOLANA_CLUSTER != "devnet". This is
  V1 Task 16 scope; mainnet initialization is out of scope and would be a
  dangerous shortcut.
- **Fail-closed on config**: if PROGRAM_ID or AUTHORITY_KEYPAIR_PATH is
  unset, or the keypair file cannot be loaded, the factory returns None
  and this script exits non-zero without ever touching RPC.

Usage
-----
    docker compose exec backend python scripts/init_devnet_program.py

Environment
-----------
    PROGRAM_ID                   (required) — deployed program address
    AUTHORITY_KEYPAIR_PATH       (required) — path to authority keypair JSON
    SOLANA_CLUSTER               (must be "devnet")
    SOLANA_RPC_URL               (must be the devnet RPC)
"""

from __future__ import annotations

import asyncio
import logging
import sys

from src.chain import get_program_client
from src.config import settings

logger = logging.getLogger("init_devnet_program")


# Strings the anchorpy / solders stack raises when an account is already
# initialized. Matching on substrings is deliberately tolerant because the
# exact error surface depends on the transport (simulation vs landed tx).
_ALREADY_INITIALIZED_MARKERS = (
    "already in use",
    "alreadyinuse",
    "already initialized",
    "accountalreadyinitialized",
    "0x0",  # Solana AccountAlreadyInUse instruction error code.
)


def _is_already_initialized_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _ALREADY_INITIALIZED_MARKERS)


async def init_program() -> int:
    """Run initialize(). Returns process exit code."""
    # Devnet-only guard. Fails closed.
    if settings.SOLANA_CLUSTER != "devnet":
        print(
            f"ERROR: SOLANA_CLUSTER={settings.SOLANA_CLUSTER!r} — this script "
            f"is devnet-only. Refusing to run.",
            file=sys.stderr,
        )
        return 2

    # RPC URL sanity check (belt-and-braces vs chain mismatch).
    rpc = settings.SOLANA_RPC_URL.lower()
    if "devnet" not in rpc:
        print(
            f"ERROR: SOLANA_RPC_URL={settings.SOLANA_RPC_URL!r} does not look "
            f"like a devnet RPC. Refusing to run.",
            file=sys.stderr,
        )
        return 2

    client = get_program_client()
    if client is None:
        print(
            "ERROR: Program client unavailable. Check PROGRAM_ID and "
            "AUTHORITY_KEYPAIR_PATH environment variables.",
            file=sys.stderr,
        )
        return 3

    config_pda, _bump = client.derive_config_pda()

    try:
        tx_sig = await client.initialize()
        print(f"init_devnet_program: SUCCESS tx_signature={tx_sig} config_pda={config_pda}")
        return 0
    except Exception as exc:
        if _is_already_initialized_error(exc):
            print(
                f"init_devnet_program: already initialized — config PDA "
                f"{config_pda} exists; no-op."
            )
            return 0
        print(f"init_devnet_program: FAILED err={exc!r}", file=sys.stderr)
        return 1


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return asyncio.run(init_program())


if __name__ == "__main__":
    sys.exit(main())

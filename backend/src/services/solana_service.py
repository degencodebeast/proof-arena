"""SolanaService — async RPC client, authority keypair, and anchorpy Provider.

Provides the connection and signing infrastructure that AgentArenaClient
needs to interact with the on-chain program.
"""

from __future__ import annotations

import json
from pathlib import Path

from anchorpy import Provider, Wallet
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts
from solders.keypair import Keypair  # type: ignore[import-untyped]
from solders.pubkey import Pubkey  # type: ignore[import-untyped]

from src.config import settings


class SolanaService:
    """Manages Solana RPC connection, authority keypair, and anchorpy Provider."""

    def __init__(
        self,
        rpc_url: str | None = None,
        authority_keypair_path: str | None = None,
    ):
        self.rpc_url = rpc_url or settings.SOLANA_RPC_URL
        self.client = AsyncClient(self.rpc_url)

        # Load authority keypair if path provided
        kp_path = authority_keypair_path or settings.AUTHORITY_KEYPAIR_PATH
        if kp_path and Path(kp_path).exists():
            with open(kp_path) as f:
                secret = json.load(f)
            self.authority = Keypair.from_bytes(bytes(secret))
        else:
            self.authority = None

        # Build anchorpy Provider/Wallet if authority is available
        if self.authority is not None:
            self.wallet = Wallet(self.authority)
            self.provider = Provider(
                self.client,
                self.wallet,
                TxOpts(
                    skip_confirmation=False,
                    preflight_commitment=Confirmed,
                ),
            )
        else:
            self.wallet = None
            self.provider = None

    @property
    def authority_pubkey(self) -> Pubkey | None:
        if self.authority is None:
            return None
        return self.authority.pubkey()

    @property
    def program_id(self) -> Pubkey:
        return Pubkey.from_string(settings.PROGRAM_ID)

    @property
    def is_ready(self) -> bool:
        """Whether the service has a valid authority and provider."""
        return self.authority is not None and self.provider is not None

    async def get_balance(self, pubkey: Pubkey) -> int:
        resp = await self.client.get_balance(pubkey)
        return resp.value

    async def get_account_info(self, pubkey: Pubkey) -> dict | None:
        resp = await self.client.get_account_info(pubkey)
        if resp.value is None:
            return None
        return {
            "lamports": resp.value.lamports,
            "owner": str(resp.value.owner),
            "data": resp.value.data,
        }

    async def confirm_transaction(self, signature: str) -> bool:
        """Wait for transaction confirmation."""
        from solders.signature import Signature  # type: ignore[import-untyped]

        sig = Signature.from_string(signature)
        resp = await self.client.confirm_transaction(sig)
        return resp.value is not None

    async def health_check(self) -> bool:
        """Check if the RPC connection is healthy."""
        try:
            resp = await self.client.get_health()
            return resp.value == "ok"
        except Exception:
            return False

    async def close(self):
        await self.client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

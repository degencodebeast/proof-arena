"""WalletService — Privy agentic wallet management for benchmark runs.

Security invariants:
- Chain/cluster is derived from config, not hardcoded. RPC and Privy signing
  must target the same network.
- ATA creation is prepended to transfers when the destination ATA doesn't exist.
- Privy responses are validated strictly — missing fields are hard failures.
- Drain results are structured per-mint, not a silent partial success.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
from solders.keypair import Keypair  # type: ignore[import-untyped]
from solders.pubkey import Pubkey  # type: ignore[import-untyped]

from src.config import settings

if TYPE_CHECKING:
    from src.services.privy_signing import PrivySigningService

logger = logging.getLogger(__name__)

PRIVY_API_BASE = "https://api.privy.io/v1"

# SPL Token and ATA Program IDs
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ATA_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")

# Solana CAIP-2 chain IDs
CLUSTER_TO_CAIP2 = {
    "devnet": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
    "mainnet-beta": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
    "testnet": "solana:4uhcVJyU9pJkvQyS88uRDiswHXSCkY3z",
}


class PrivyAPIError(Exception):
    """Raised when a Privy API call fails."""

    def __init__(self, status_code: int, detail: str, operation: str):
        self.status_code = status_code
        self.detail = detail
        self.operation = operation
        super().__init__(f"Privy {operation} failed ({status_code}): {detail}")


class WalletFundingError(Exception):
    """Raised when treasury funding fails."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"Wallet funding failed: {detail}")


class ChainMismatchError(Exception):
    """Raised when RPC and signing target different networks."""

    def __init__(self, rpc_url: str, cluster: str):
        super().__init__(
            f"Chain mismatch: RPC URL '{rpc_url}' does not match "
            f"configured cluster '{cluster}'"
        )


@dataclass
class DrainMintResult:
    """Result of draining one mint from a wallet."""

    mint: str
    balance: int
    success: bool
    signature: str | None = None
    error: str | None = None


@dataclass
class DrainResult:
    """Structured result of draining all tokens from a wallet."""

    results: list[DrainMintResult] = field(default_factory=list)

    @property
    def fully_drained(self) -> bool:
        return all(r.success for r in self.results)

    @property
    def signatures(self) -> list[str]:
        return [r.signature for r in self.results if r.signature]

    @property
    def failed_mints(self) -> list[str]:
        return [r.mint for r in self.results if not r.success]


class WalletService:
    """Manages Privy agentic wallets for benchmark execution."""

    # RPC URL substrings that identify each cluster
    CLUSTER_RPC_MARKERS = {
        "devnet": "devnet",
        "mainnet-beta": "mainnet",
        "testnet": "testnet",
    }

    def __init__(
        self,
        privy_app_id: str | None = None,
        privy_app_secret: str | None = None,
        solana_rpc_url: str | None = None,
        solana_cluster: str | None = None,
        treasury_keypair: Keypair | None = None,
        usdc_mint: Pubkey | None = None,
        signing_service: "PrivySigningService | None" = None,
    ):
        self.app_id = privy_app_id or settings.PRIVY_APP_ID
        self.app_secret = privy_app_secret or settings.PRIVY_APP_SECRET
        self.rpc_url = solana_rpc_url or settings.SOLANA_RPC_URL
        self.cluster = solana_cluster or settings.SOLANA_CLUSTER
        # V2 Task 9: PrivySigningService is required for create_hosted_wallet
        # but optional for existing V1 callers that only use benchmark wallets.
        self.signing_service = signing_service

        # Load treasury keypair from config if not injected
        if treasury_keypair is not None:
            self.treasury_keypair = treasury_keypair
        elif settings.TREASURY_KEYPAIR_PATH:
            import json
            from pathlib import Path

            kp_path = Path(settings.TREASURY_KEYPAIR_PATH).expanduser()
            if kp_path.exists():
                with open(kp_path) as f:
                    self.treasury_keypair = Keypair.from_bytes(bytes(json.load(f)))
            else:
                self.treasury_keypair = None
        else:
            self.treasury_keypair = None

        # Load USDC mint from config if not injected
        if usdc_mint is not None:
            self.usdc_mint = usdc_mint
        elif settings.USDC_MINT:
            self.usdc_mint = Pubkey.from_string(settings.USDC_MINT)
        else:
            self.usdc_mint = None

        # Derive CAIP2 from cluster config — fail if unknown
        if self.cluster not in CLUSTER_TO_CAIP2:
            raise ValueError(
                f"Unknown cluster '{self.cluster}'. "
                f"Must be one of: {list(CLUSTER_TO_CAIP2.keys())}"
            )
        self.caip2 = CLUSTER_TO_CAIP2[self.cluster]

        # Cross-network safety: RPC URL must match declared cluster
        self._validate_rpc_cluster_match()

        self.client = httpx.AsyncClient(
            base_url=PRIVY_API_BASE,
            auth=(self.app_id, self.app_secret),
            headers={
                "privy-app-id": self.app_id,
                "Content-Type": "application/json",
            },
            timeout=30.0,
            http2=True,
        )

    def _validate_rpc_cluster_match(self) -> None:
        """Verify RPC URL matches the declared cluster. Prevents signing
        on one network while reading state from another."""
        expected_marker = self.CLUSTER_RPC_MARKERS.get(self.cluster)
        if expected_marker is None:
            return  # Unknown cluster already caught above

        rpc_lower = self.rpc_url.lower()
        # Special case: mainnet URLs may use "mainnet-beta" or just "mainnet"
        if self.cluster == "mainnet-beta":
            if "devnet" in rpc_lower or "testnet" in rpc_lower:
                raise ChainMismatchError(self.rpc_url, self.cluster)
        else:
            # For devnet/testnet: the RPC URL must contain the cluster name,
            # OR must not contain any other cluster name (custom RPC)
            other_clusters = [
                m for c, m in self.CLUSTER_RPC_MARKERS.items()
                if c != self.cluster
            ]
            for other in other_clusters:
                if other in rpc_lower and expected_marker not in rpc_lower:
                    raise ChainMismatchError(self.rpc_url, self.cluster)

    @property
    def treasury_pubkey(self) -> Pubkey | None:
        if self.treasury_keypair is None:
            return None
        return self.treasury_keypair.pubkey()

    # -------------------------------------------------------------------
    # Wallet creation
    # -------------------------------------------------------------------

    async def create_benchmark_wallet(
        self, challenge_id: int, agent_id: int
    ) -> dict[str, str]:
        """Create a Privy wallet for a benchmark run.

        Returns dict with 'id' and 'address'. Raises on missing fields.
        """
        resp = await self.client.post(
            "/wallets",
            json={
                "chain_type": "solana",
                "name": f"benchmark_{challenge_id}_{agent_id}",
            },
        )
        if resp.status_code != 200:
            raise PrivyAPIError(
                resp.status_code, resp.text, "create_benchmark_wallet",
            )
        data = resp.json()
        wallet_id = data.get("id")
        address = data.get("address")
        if not wallet_id or not address:
            raise PrivyAPIError(
                200,
                f"Missing wallet fields: id={wallet_id}, address={address}",
                "create_benchmark_wallet",
            )
        return {"id": wallet_id, "address": address}

    # -------------------------------------------------------------------
    # V2 Task 9 — hosted agentic-wallet creation (policy-bound)
    # -------------------------------------------------------------------

    async def create_hosted_wallet(
        self,
        policy_id: str,
        authorization_pubkey: str,
        chain_type: str = "solana",
        cluster: str = "devnet",
    ) -> dict[str, str]:
        """Create a policy-bound hosted Privy wallet for V2.

        Matches the Phase 0-validated posture byte-equal: ``policy_ids`` as
        an array (plural), ``owner={"public_key": <base64 DER P-256 SPKI>}``,
        and a ``privy-authorization-signature`` header computed by the
        injected ``PrivySigningService`` over the **full URL**
        ``https://api.privy.io/v1/wallets``.

        Layer 1 of the three-layer mainnet guard lives here — ``cluster``
        MUST be ``"devnet"``; anything else raises ``ChainMismatchError``
        before any network work.

        Returns ``{"id": <wallet_id>, "address": <solana_pubkey>}``.

        Raises:
            ChainMismatchError: ``cluster != "devnet"``.
            ValueError: ``signing_service`` was not injected.
            PrivyAPIError: non-200 status, or 200 with missing id/address.
        """
        # Layer 1 mainnet guard — strict; only "devnet" passes.
        # Primary: the service instance itself must be wired for devnet.
        # Defense-in-depth: the method-level ``cluster`` arg must also be devnet.
        if self.cluster != "devnet":
            raise ChainMismatchError(self.rpc_url, self.cluster)
        if cluster != "devnet":
            raise ChainMismatchError(self.rpc_url, cluster)

        if self.signing_service is None:
            raise ValueError(
                "PrivySigningService is required for create_hosted_wallet. "
                "Inject one via WalletService(signing_service=...)."
            )

        body = {
            "chain_type": chain_type,
            "owner": {"public_key": authorization_pubkey},
            "policy_ids": [policy_id],
        }

        signature = self.signing_service.sign_request(
            method="POST",
            url=f"{PRIVY_API_BASE}/wallets",
            body=body,
        )

        resp = await self.client.post(
            "/wallets",
            json=body,
            headers={"privy-authorization-signature": signature},
        )
        if resp.status_code != 200:
            raise PrivyAPIError(
                resp.status_code, resp.text, "create_hosted_wallet"
            )
        data = resp.json()
        wallet_id = data.get("id")
        address = data.get("address")
        if not wallet_id or not address:
            raise PrivyAPIError(
                200,
                f"Missing wallet fields: id={wallet_id}, address={address}",
                "create_hosted_wallet",
            )
        logger.info(
            "Created hosted wallet %s at %s with policy %s",
            wallet_id,
            address,
            policy_id,
        )
        return {"id": wallet_id, "address": address}

    # -------------------------------------------------------------------
    # Transaction signing
    # -------------------------------------------------------------------

    async def sign_and_send_transaction(
        self, wallet_id: str, tx_bytes: bytes
    ) -> str:
        """Sign and send via Privy. Returns tx signature. Raises on failure."""
        encoded_tx = base64.b64encode(tx_bytes).decode("ascii")
        resp = await self.client.post(
            f"/wallets/{wallet_id}/rpc",
            json={
                "method": "signAndSendTransaction",
                "caip2": self.caip2,
                "params": {
                    "transaction": encoded_tx,
                    "encoding": "base64",
                },
            },
        )
        if resp.status_code != 200:
            raise PrivyAPIError(
                resp.status_code, resp.text, "sign_and_send_transaction",
            )
        data = resp.json()
        tx_hash = data.get("data", {}).get("hash")
        if not tx_hash:
            raise PrivyAPIError(
                200,
                f"Missing tx hash in response: {data}",
                "sign_and_send_transaction",
            )
        return tx_hash

    async def sign_transaction(
        self, wallet_id: str, tx_bytes: bytes
    ) -> bytes:
        """Sign without sending. Returns signed tx bytes. Raises on failure."""
        encoded_tx = base64.b64encode(tx_bytes).decode("ascii")
        resp = await self.client.post(
            f"/wallets/{wallet_id}/rpc",
            json={
                "method": "signTransaction",
                "params": {
                    "transaction": encoded_tx,
                    "encoding": "base64",
                },
            },
        )
        if resp.status_code != 200:
            raise PrivyAPIError(
                resp.status_code, resp.text, "sign_transaction",
            )
        data = resp.json()
        signed_b64 = data.get("data", {}).get("signed_transaction")
        if not signed_b64:
            raise PrivyAPIError(
                200,
                f"Missing signed_transaction in response: {data}",
                "sign_transaction",
            )
        return base64.b64decode(signed_b64)

    # -------------------------------------------------------------------
    # Token balances
    # -------------------------------------------------------------------

    async def get_token_balances(
        self, wallet_address: str
    ) -> dict[str, int]:
        """Read token account balances via Solana RPC.

        Returns {mint_address: balance_in_base_units}. Excludes zero balances.
        """
        async with httpx.AsyncClient(timeout=15.0) as rpc_client:
            resp = await rpc_client.post(
                self.rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTokenAccountsByOwner",
                    "params": [
                        wallet_address,
                        {"programId": str(TOKEN_PROGRAM_ID)},
                        {"encoding": "jsonParsed"},
                    ],
                },
            )
        if resp.status_code != 200:
            raise PrivyAPIError(resp.status_code, resp.text, "get_token_balances")

        result = resp.json().get("result", {})
        balances: dict[str, int] = {}
        for account in result.get("value", []):
            parsed = account.get("account", {}).get("data", {}).get("parsed", {})
            info = parsed.get("info", {})
            mint = info.get("mint", "")
            amount = int(info.get("tokenAmount", {}).get("amount", "0"))
            if mint and amount > 0:
                balances[mint] = amount
        return balances

    # -------------------------------------------------------------------
    # Treasury funding (USDC transfer to benchmark wallet)
    # -------------------------------------------------------------------

    async def fund_wallet(
        self, wallet_address: str, amount_usdc: int
    ) -> str:
        """Transfer USDC from treasury to benchmark wallet.

        Creates the destination ATA if it doesn't exist (idempotent).
        """
        if self.treasury_keypair is None:
            raise WalletFundingError("No treasury keypair configured")
        if self.usdc_mint is None:
            raise WalletFundingError("No USDC mint configured")

        from solders.hash import Hash  # type: ignore[import-untyped]
        from solders.instruction import AccountMeta, Instruction  # type: ignore[import-untyped]
        from solders.message import Message  # type: ignore[import-untyped]
        from solders.system_program import ID as SYS_PROGRAM_ID  # type: ignore[import-untyped]
        from solders.transaction import Transaction  # type: ignore[import-untyped]

        treasury_pk = self.treasury_keypair.pubkey()
        dest_pk = Pubkey.from_string(wallet_address)
        source_ata = self._derive_ata(treasury_pk, self.usdc_mint)
        dest_ata = self._derive_ata(dest_pk, self.usdc_mint)

        instructions = []

        # Create destination ATA if needed (idempotent)
        create_ata_ix = Instruction(
            program_id=ATA_PROGRAM_ID,
            accounts=[
                AccountMeta(treasury_pk, is_signer=True, is_writable=True),
                AccountMeta(dest_ata, is_signer=False, is_writable=True),
                AccountMeta(dest_pk, is_signer=False, is_writable=False),
                AccountMeta(self.usdc_mint, is_signer=False, is_writable=False),
                AccountMeta(SYS_PROGRAM_ID, is_signer=False, is_writable=False),
                AccountMeta(TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            ],
            data=bytes([1]),  # CreateIdempotent instruction index
        )
        instructions.append(create_ata_ix)

        # SPL Transfer
        transfer_data = bytes([3]) + amount_usdc.to_bytes(8, "little")
        transfer_ix = Instruction(
            program_id=TOKEN_PROGRAM_ID,
            accounts=[
                AccountMeta(source_ata, is_signer=False, is_writable=True),
                AccountMeta(dest_ata, is_signer=False, is_writable=True),
                AccountMeta(treasury_pk, is_signer=True, is_writable=False),
            ],
            data=transfer_data,
        )
        instructions.append(transfer_ix)

        blockhash = await self._get_blockhash()
        msg = Message.new_with_blockhash(instructions, treasury_pk, Hash.from_string(blockhash))
        tx = Transaction.new_unsigned(msg)
        tx.sign([self.treasury_keypair], Hash.from_string(blockhash))

        return await self._send_raw_transaction(tx)

    # -------------------------------------------------------------------
    # Drain wallet back to treasury
    # -------------------------------------------------------------------

    async def drain_wallet(
        self, wallet_id: str, wallet_address: str, treasury_address: str,
    ) -> DrainResult:
        """Transfer all tokens from benchmark wallet back to treasury.

        Returns structured DrainResult with per-mint outcomes.
        Does NOT silently swallow failures.
        """
        balances = await self.get_token_balances(wallet_address)
        if not balances:
            return DrainResult()

        from solders.hash import Hash  # type: ignore[import-untyped]
        from solders.instruction import AccountMeta, Instruction  # type: ignore[import-untyped]
        from solders.message import Message  # type: ignore[import-untyped]
        from solders.system_program import ID as SYS_PROGRAM_ID  # type: ignore[import-untyped]
        from solders.transaction import Transaction  # type: ignore[import-untyped]

        wallet_pk = Pubkey.from_string(wallet_address)
        treasury_pk = Pubkey.from_string(treasury_address)
        result = DrainResult()

        for mint_str, balance in balances.items():
            if balance == 0:
                continue

            mint_pk = Pubkey.from_string(mint_str)
            source_ata = self._derive_ata(wallet_pk, mint_pk)
            dest_ata = self._derive_ata(treasury_pk, mint_pk)

            instructions = []

            # Create treasury ATA if needed (idempotent)
            # Payer is the benchmark wallet (signed by Privy)
            create_ata_ix = Instruction(
                program_id=ATA_PROGRAM_ID,
                accounts=[
                    AccountMeta(wallet_pk, is_signer=True, is_writable=True),
                    AccountMeta(dest_ata, is_signer=False, is_writable=True),
                    AccountMeta(treasury_pk, is_signer=False, is_writable=False),
                    AccountMeta(mint_pk, is_signer=False, is_writable=False),
                    AccountMeta(SYS_PROGRAM_ID, is_signer=False, is_writable=False),
                    AccountMeta(TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
                ],
                data=bytes([1]),
            )
            instructions.append(create_ata_ix)

            transfer_data = bytes([3]) + balance.to_bytes(8, "little")
            transfer_ix = Instruction(
                program_id=TOKEN_PROGRAM_ID,
                accounts=[
                    AccountMeta(source_ata, is_signer=False, is_writable=True),
                    AccountMeta(dest_ata, is_signer=False, is_writable=True),
                    AccountMeta(wallet_pk, is_signer=True, is_writable=False),
                ],
                data=transfer_data,
            )
            instructions.append(transfer_ix)

            try:
                blockhash = await self._get_blockhash()
                msg = Message.new_with_blockhash(
                    instructions, wallet_pk, Hash.from_string(blockhash)
                )
                tx = Transaction.new_unsigned(msg)
                tx_bytes = bytes(tx)

                sig = await self.sign_and_send_transaction(wallet_id, tx_bytes)
                result.results.append(DrainMintResult(
                    mint=mint_str, balance=balance, success=True, signature=sig,
                ))
            except (PrivyAPIError, Exception) as e:
                logger.error("drain_wallet: failed mint %s: %s", mint_str, e)
                result.results.append(DrainMintResult(
                    mint=mint_str, balance=balance, success=False,
                    error=str(e),
                ))

        return result

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    async def _get_blockhash(self) -> str:
        """Get latest blockhash from RPC."""
        async with httpx.AsyncClient(timeout=15.0) as rpc_client:
            resp = await rpc_client.post(
                self.rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getLatestBlockhash",
                    "params": [{"commitment": "finalized"}],
                },
            )
        if resp.status_code != 200:
            raise WalletFundingError(f"Failed to get blockhash: {resp.text}")
        blockhash = resp.json().get("result", {}).get("value", {}).get("blockhash")
        if not blockhash:
            raise WalletFundingError("No blockhash in RPC response")
        return blockhash

    async def _send_raw_transaction(self, tx: Any) -> str:
        """Send a signed transaction via RPC."""
        tx_b64 = base64.b64encode(bytes(tx)).decode("ascii")
        async with httpx.AsyncClient(timeout=30.0) as rpc_client:
            resp = await rpc_client.post(
                self.rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendTransaction",
                    "params": [tx_b64, {"encoding": "base64"}],
                },
            )
        if resp.status_code != 200:
            raise WalletFundingError(f"sendTransaction failed: {resp.text}")
        result = resp.json()
        if "error" in result:
            raise WalletFundingError(f"RPC error: {result['error']}")
        sig = result.get("result", "")
        if not sig:
            raise WalletFundingError("No signature in sendTransaction response")
        return sig

    @staticmethod
    def _derive_ata(owner: Pubkey, mint: Pubkey) -> Pubkey:
        """Derive the associated token account address."""
        pda, _ = Pubkey.find_program_address(
            [bytes(owner), bytes(TOKEN_PROGRAM_ID), bytes(mint)],
            ATA_PROGRAM_ID,
        )
        return pda

    async def close(self):
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

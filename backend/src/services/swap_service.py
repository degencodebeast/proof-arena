"""OrcaSwapService — build unsigned Orca Whirlpools swap transactions (devnet).

Implementation decision: **Option A — Node subprocess invoking
``@orca-so/whirlpools`` TS SDK.** See ``.taskmaster/docs/task11-b6-decision.md``
for the B-6 gate rationale.

Contract:
- Python owns the service surface (typed errors, cluster guard, logging).
- Node (``scripts/orca_swap.js``) owns swap-ix construction using the
  SDK-maintained canonical path proven in Phase 0.
- Python → Node: CLI flags (``--input-mint``, ``--output-mint``, ``--amount``,
  ``--slippage-bps``, ``--wallet-pubkey``, ``--rpc-url``).
- Node → Python: one-line base64 string on stdout; failures exit non-zero
  with a reason on stderr.

``prepare_swap_tx`` returns **unsigned** transaction bytes. Signing happens
at the wallet-service layer (Privy enclave in V2 hosted path) — never here.
"""

from __future__ import annotations

import asyncio
import base64
import logging

logger = logging.getLogger(__name__)

_SUBPROCESS_TIMEOUT_SECS_DEFAULT = 30


class OrcaSwapError(Exception):
    """Base class for OrcaSwapService failures."""


class InvalidPoolError(OrcaSwapError):
    """Pool or mint configuration rejected by the Orca SDK.

    Raised when the Node helper's stderr indicates the Whirlpool account
    or mint pair is unusable (e.g. wrong address, uninitialized pool).
    """


class OrcaSwapService:
    """Build unsigned Orca Whirlpools swap transactions on devnet.

    V2 is devnet-only. ``cluster`` must be ``"devnet"``; anything else raises
    ``RuntimeError`` at construction time — this is Layer 2 of the three-layer
    mainnet guard (wallet-service / runtime / Privy-enclave policy being the
    other two). No hosted V2 flow may target mainnet.
    """

    def __init__(
        self,
        rpc_url: str,
        cluster: str = "devnet",
        script_path: str = "scripts/orca_swap.js",
        timeout_secs: int = _SUBPROCESS_TIMEOUT_SECS_DEFAULT,
        pool_address: str = "",
    ) -> None:
        if cluster != "devnet":
            raise RuntimeError(
                f"OrcaSwapService only supports devnet in V2; got cluster={cluster!r}"
            )
        self.rpc_url = rpc_url
        self.cluster = cluster
        self.script_path = script_path
        self.timeout_secs = timeout_secs
        # V2 is scoped to the Phase-0-locked SOL/devUSDC Whirlpool
        # `3KBZiL2g8C7tiJ32hTv5v3KM7aK9htpqTw4cTXz1HvPt`. Callers pass this
        # in from `settings.V2_HOSTED_SWAP_POOL`; leaving it empty is a
        # configuration error surfaced at swap time as InvalidPoolError.
        self.pool_address = pool_address

    async def prepare_swap_tx(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int,
        wallet_pubkey: str,
    ) -> bytes:
        """Construct an unsigned Orca Whirlpools swap and return its bytes.

        Returns the base64-decoded bytes of the unsigned versioned
        transaction emitted by ``scripts/orca_swap.js``. The returned
        value is never signed — the caller (e.g. wallet service) is
        responsible for signing.
        """
        if not self.pool_address:
            raise InvalidPoolError(
                "pool_address not configured; pass pool_address=... to "
                "OrcaSwapService or set settings.V2_HOSTED_SWAP_POOL"
            )

        argv = (
            "node",
            self.script_path,
            "--input-mint", input_mint,
            "--output-mint", output_mint,
            "--amount", str(amount),
            "--slippage-bps", str(slippage_bps),
            "--wallet-pubkey", wallet_pubkey,
            "--rpc-url", self.rpc_url,
            "--pool", self.pool_address,
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise OrcaSwapError(
                f"node runtime unavailable; install Node to use OrcaSwapService: {e}"
            ) from e

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.timeout_secs,
            )
        except asyncio.TimeoutError as e:
            # Don't leave the Node process lingering.
            proc.kill()
            try:
                await proc.wait()
            except Exception:  # best-effort; primary error already captured
                pass
            raise OrcaSwapError(
                f"orca_swap helper timed out after {self.timeout_secs}s"
            ) from e

        if proc.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            logger.warning(
                "orca_swap helper failed (exit=%s): %s",
                proc.returncode,
                stderr_text,
            )
            if _looks_like_pool_error(stderr_text):
                raise InvalidPoolError(stderr_text)
            raise OrcaSwapError(stderr_text or f"exit={proc.returncode}")

        payload = stdout.decode("utf-8", errors="replace").strip()
        try:
            return base64.b64decode(payload, validate=True)
        except (ValueError, base64.binascii.Error) as e:  # type: ignore[attr-defined]
            raise OrcaSwapError(
                f"orca_swap helper returned malformed base64 stdout: {e}"
            ) from e


def _looks_like_pool_error(stderr_text: str) -> bool:
    """Classify a Node stderr message as pool/mint-related vs generic.

    Deliberately narrow substring match; the wallet-service side pattern
    is the same (cheap keyword classification, not stderr parsing).
    """
    lowered = stderr_text.lower()
    return "whirlpool" in lowered or "pool" in lowered or "mint" in lowered

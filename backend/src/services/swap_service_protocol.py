"""SwapServiceProtocol — runtime-checkable Protocol for the runner's swap-service boundary.

Introduced in Task 37 to lift the hard coupling between
``RunnerService`` and concrete ``JupiterService``. Both
``JupiterService`` (V1) and ``OrcaSwapService`` (V2 hosted) satisfy
this protocol; the runner driver and the ``ActionValidator`` depend
only on the protocol surface, never on the concrete classes.

Four methods, deliberately narrow:

- ``get_quotes(input_mint, output_mint, amount, slippage_bps)`` —
  fetch one or more quotes for a mint pair + amount. Implementations
  cache each quote under a fresh ``QuoteOption.quote_id`` and return
  the list.
- ``get_cached_quote(quote_id)`` — dict-like lookup; returns ``None``
  for unknown ids.
- ``is_quote_fresh(quote_id, max_age_secs=None)`` — age check against
  ``QuoteOption.fetched_at``.
- ``prepare_swap_transaction(quote_id, user_public_key,
  max_slippage_bps=None)`` — build unsigned versioned-transaction
  bytes for the cached quote, bound to the given wallet. Signing
  happens downstream at the wallet-service layer (Privy enclave in
  V2 hosted path, or the local wallet signer in V1).

Invariants (see ``.taskmaster/docs/task37-edge-case-spec.md`` §2):
- ``QuoteOption`` is the sole exchange type. Its ``route_data`` dict
  is opaque to callers — implementations use it however they like
  (Jupiter stores the Jupiter API route; Orca stores its Node-helper
  params).
- ``out_amount`` is best-effort. V1 Jupiter reports a real estimate;
  V2 Orca reports ``0`` as a documented lossy placeholder (the Node
  helper needs a wallet to compute it, and ``get_quotes`` happens
  before the wallet is locked in).
- Runner never introspects ``route_data``; it flows opaquely from
  quote → prepare_swap_transaction.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.services.jupiter_service import QuoteOption  # re-exported

__all__ = ["QuoteOption", "SwapServiceProtocol"]


@runtime_checkable
class SwapServiceProtocol(Protocol):
    """Runner's swap-service boundary. See module docstring."""

    async def get_quotes(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 50,
    ) -> list[QuoteOption]:
        ...

    def get_cached_quote(self, quote_id: str) -> QuoteOption | None:
        ...

    def is_quote_fresh(
        self, quote_id: str, max_age_secs: int | None = None
    ) -> bool:
        ...

    async def prepare_swap_transaction(
        self,
        quote_id: str,
        user_public_key: str,
        max_slippage_bps: int | None = None,
    ) -> bytes:
        ...

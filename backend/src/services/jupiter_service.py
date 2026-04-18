"""JupiterService — Jupiter Swap API integration for benchmark execution.

Uses the Jupiter Legacy Swap API (separate quote → swap steps):
- GET  /swap/v1/quote   — fetch quote
- POST /swap/v1/swap    — get unsigned swap transaction

Base URL: https://api.jup.ag

Quote lifecycle:
1. get_quotes() fetches a quote and assigns a platform quote_id
2. Quote is cached with fetch timestamp
3. prepare_swap_transaction() checks freshness before building swap tx
4. Stale quotes (> QUOTE_MAX_AGE_SECS) are rejected

NOTE: Jupiter devnet support may be limited. Quote/swap endpoints
target mainnet by default. For devnet testing, mock responses are
recommended.
"""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from src.config import settings

logger = logging.getLogger(__name__)

JUPITER_BASE_URL = "https://api.jup.ag"


class StaleQuoteError(Exception):
    """Raised when a quote is too old for execution."""

    def __init__(self, quote_id: str, age_secs: float, max_age_secs: int):
        self.quote_id = quote_id
        self.age_secs = age_secs
        self.max_age_secs = max_age_secs
        super().__init__(
            f"Quote {quote_id} is stale ({age_secs:.1f}s > {max_age_secs}s)"
        )


class JupiterAPIError(Exception):
    """Raised when a Jupiter API call fails."""

    def __init__(self, status_code: int, detail: str, operation: str):
        self.status_code = status_code
        self.detail = detail
        self.operation = operation
        super().__init__(f"Jupiter {operation} failed ({status_code}): {detail}")


class QuoteOption(BaseModel):
    """A cached quote option with platform-assigned ID."""

    model_config = ConfigDict(frozen=True)

    quote_id: str
    input_mint: str
    output_mint: str
    in_amount: int
    out_amount: int
    slippage_bps: int
    fetched_at: str  # ISO 8601 UTC
    route_data: dict[str, Any]  # Full Jupiter quoteResponse for swap


class JupiterService:
    """Jupiter Swap API client with quote caching and freshness validation."""

    def __init__(
        self,
        base_url: str | None = None,
        max_age_secs: int | None = None,
    ):
        self.base_url = base_url or settings.JUPITER_API_URL or JUPITER_BASE_URL
        self.max_age_secs = max_age_secs or settings.QUOTE_MAX_AGE_SECS
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=15.0,
            http2=True,
        )
        self._quote_cache: dict[str, QuoteOption] = {}

    async def get_quotes(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 50,
    ) -> list[QuoteOption]:
        """Fetch Jupiter quotes and assign platform quote_ids.

        Returns a list of QuoteOption (currently one per request).
        Each quote is cached for freshness validation.
        """
        resp = await self.client.get(
            "/swap/v1/quote",
            params={
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": str(amount),
                "slippageBps": slippage_bps,
                "restrictIntermediateTokens": "true",
            },
        )
        if resp.status_code != 200:
            raise JupiterAPIError(
                resp.status_code, resp.text, "get_quotes"
            )

        route_data = resp.json()
        quote_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        quote = QuoteOption(
            quote_id=quote_id,
            input_mint=input_mint,
            output_mint=output_mint,
            in_amount=amount,
            out_amount=int(route_data.get("outAmount", 0)),
            slippage_bps=slippage_bps,
            fetched_at=now,
            route_data=route_data,
        )
        self._quote_cache[quote_id] = quote

        return [quote]

    def get_cached_quote(self, quote_id: str) -> QuoteOption | None:
        """Retrieve a cached quote by platform ID."""
        return self._quote_cache.get(quote_id)

    def is_quote_fresh(
        self, quote_id: str, max_age_secs: int | None = None
    ) -> bool:
        """Check if a quote is within the freshness window."""
        quote = self._quote_cache.get(quote_id)
        if quote is None:
            return False
        max_age = max_age_secs or self.max_age_secs
        fetched = datetime.fromisoformat(quote.fetched_at)
        age = (datetime.now(timezone.utc) - fetched).total_seconds()
        return age < max_age

    def validate_quote_freshness(
        self, quote_id: str, max_age_secs: int | None = None
    ) -> None:
        """Raise StaleQuoteError if quote is stale or not found."""
        quote = self._quote_cache.get(quote_id)
        if quote is None:
            raise StaleQuoteError(quote_id, float("inf"), self.max_age_secs)
        max_age = max_age_secs or self.max_age_secs
        fetched = datetime.fromisoformat(quote.fetched_at)
        age = (datetime.now(timezone.utc) - fetched).total_seconds()
        if age >= max_age:
            raise StaleQuoteError(quote_id, age, max_age)

    async def prepare_swap_transaction(
        self,
        quote_id: str,
        user_public_key: str,
        max_slippage_bps: int | None = None,
    ) -> bytes:
        """Get unsigned swap transaction bytes from Jupiter.

        Validates quote freshness before requesting the swap tx.
        Returns raw transaction bytes for signing.
        """
        self.validate_quote_freshness(quote_id)

        quote = self._quote_cache[quote_id]
        route_data = dict(quote.route_data)

        # Override slippage if specified
        if max_slippage_bps is not None:
            route_data["slippageBps"] = max_slippage_bps

        resp = await self.client.post(
            "/swap/v1/swap",
            json={
                "quoteResponse": route_data,
                "userPublicKey": user_public_key,
                "dynamicSlippage": (
                    {"maxBps": max_slippage_bps}
                    if max_slippage_bps is not None
                    else None
                ),
            },
        )
        if resp.status_code != 200:
            raise JupiterAPIError(
                resp.status_code, resp.text, "prepare_swap_transaction"
            )

        swap_data = resp.json()
        swap_tx_b64 = swap_data.get("swapTransaction", "")
        if not swap_tx_b64:
            raise JupiterAPIError(
                200,
                "No swapTransaction in response",
                "prepare_swap_transaction",
            )
        return base64.b64decode(swap_tx_b64)

    def clear_stale_quotes(self, max_age_secs: int | None = None) -> int:
        """Remove quotes older than max_age from cache.

        Returns count of removed quotes. Uses the configured
        QUOTE_MAX_AGE_SECS if no override is provided.
        """
        max_age = max_age_secs if max_age_secs is not None else self.max_age_secs
        now = datetime.now(timezone.utc)
        stale_ids = []
        for qid, quote in self._quote_cache.items():
            fetched = datetime.fromisoformat(quote.fetched_at)
            if (now - fetched).total_seconds() >= max_age:
                stale_ids.append(qid)
        for qid in stale_ids:
            del self._quote_cache[qid]
        return len(stale_ids)

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

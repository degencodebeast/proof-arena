"""get_quotes tool — fetches Jupiter quotes with allowed-pair enforcement.

Stateless closure factory: inject JupiterService and allowed_pairs,
returns a tool function with pair validation before calling Jupiter.
"""

from __future__ import annotations

import json

from agno.tools import tool

from src.services.jupiter_service import JupiterService


def create_get_quotes_tool(
    jupiter_service: JupiterService,
    allowed_pairs: list[tuple[str, str]],
):
    """Create a get_quotes tool bound to a JupiterService and allowed pairs."""

    @tool(description="Get available swap quotes from Jupiter for allowed token pairs.")
    async def get_quotes(input_mint: str, output_mint: str, amount: int) -> str:
        """Fetch swap quotes for a token pair.

        Args:
            input_mint: The mint address of the token to swap from.
            output_mint: The mint address of the token to swap to.
            amount: The amount of input tokens in base units.

        Returns:
            JSON with quote options including quote_id, or error if pair not allowed.
        """
        if allowed_pairs and (input_mint, output_mint) not in allowed_pairs:
            return json.dumps({
                "error": "Token pair not allowed in this challenge",
                "input_mint": input_mint,
                "output_mint": output_mint,
            })

        try:
            quotes = await jupiter_service.get_quotes(
                input_mint, output_mint, amount, slippage_bps=100,
            )
            return json.dumps([q.model_dump() for q in quotes])
        except Exception as e:
            return json.dumps({"error": str(e)})

    return get_quotes

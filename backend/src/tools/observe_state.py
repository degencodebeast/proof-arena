"""observe_state tool — reads current portfolio state from WalletService.

Stateless closure factory: inject WalletService and wallet_address,
returns a tool function the Agno agent can call.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from agno.tools import tool

from src.services.wallet_service import WalletService


def create_observe_state_tool(
    wallet_service: WalletService, wallet_address: str
):
    """Create an observe_state tool bound to a specific wallet."""

    @tool(description="Observe current portfolio state including all token balances.")
    async def observe_state() -> str:
        """Read the current token balances for the benchmark wallet."""
        balances = await wallet_service.get_token_balances(wallet_address)
        state = {
            "balances": {mint: amount for mint, amount in balances.items()},
            "wallet_address": wallet_address,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return json.dumps(state)

    return observe_state

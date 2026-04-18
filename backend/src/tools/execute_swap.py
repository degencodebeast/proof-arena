"""execute_swap tool — validates, prepares, and executes a swap.

Stateless closure factory: inject services, validator, and a state accessor
so validation receives the real current challenge/run state.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from agno.tools import tool

from src.db.schemas import AgentAction, AgentActionType
from src.integrity import ValidationResult
from src.services.jupiter_service import JupiterService, StaleQuoteError
from src.services.wallet_service import WalletService


def create_execute_swap_tool(
    jupiter_service: JupiterService,
    wallet_service: WalletService,
    wallet_id: str,
    wallet_address: str,
    action_validator: object | None = None,
    get_current_state: Callable[[], dict[str, Any]] | None = None,
):
    """Create an execute_swap tool bound to services and wallet.

    Args:
        action_validator: Optional ActionValidator protocol implementation.
        get_current_state: Callable returning the current challenge/run state
            dict for validation. If None, validation uses a minimal state.
    """

    @tool(description="Execute a swap using a previously obtained quote.")
    async def execute_swap(quote_id: str, max_slippage_bps: int) -> str:
        """Execute a token swap.

        Args:
            quote_id: The platform quote_id from a previous get_quotes call.
            max_slippage_bps: Maximum acceptable slippage in basis points.

        Returns:
            JSON with {executed, tx_signature} or {error, executed: false}.
        """
        # Build the action
        try:
            action = AgentAction(
                type=AgentActionType.EXECUTE_SWAP,
                params={"quote_id": quote_id, "max_slippage_bps": max_slippage_bps},
            )
        except Exception as e:
            return json.dumps({"error": f"Invalid action params: {e}", "executed": False})

        # Validate with real state — fail closed if validator exists without state
        if action_validator is not None:
            if get_current_state is None:
                return json.dumps({
                    "error": "Validator configured but no state accessor provided",
                    "executed": False,
                })
            state = get_current_state()
            validation = await action_validator.validate(
                action.model_dump(), state,
            )
            if isinstance(validation, ValidationResult) and not validation.valid:
                return json.dumps({"error": validation.reason, "executed": False})
            elif isinstance(validation, dict) and not validation.get("valid", True):
                return json.dumps({
                    "error": validation.get("reason", "Validation failed"),
                    "executed": False,
                })

        # Prepare swap transaction
        try:
            tx_bytes = await jupiter_service.prepare_swap_transaction(
                quote_id, wallet_address, max_slippage_bps,
            )
        except StaleQuoteError as e:
            return json.dumps({"error": f"Stale quote: {e}", "executed": False})
        except Exception as e:
            return json.dumps({"error": f"Swap preparation failed: {e}", "executed": False})

        # Sign and send
        try:
            signature = await wallet_service.sign_and_send_transaction(
                wallet_id, tx_bytes,
            )
            return json.dumps({
                "executed": True,
                "tx_signature": signature,
                "quote_id": quote_id,
            })
        except Exception as e:
            return json.dumps({"error": f"Transaction send failed: {e}", "executed": False})

    return execute_swap

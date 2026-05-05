# agent-rank/backend/tests/integration/test_swap_runner_path_unchanged.py
"""REGRESSION-LOCK — swap path still works after runner patches 2-5.

This test is expected to PASS on its FIRST run after the patches land.
If it fails on the first run, it means the patches broke V1 swap behavior.

Verified invariants:
- swap_service.prepare_swap_transaction is called at least once (EXECUTE_SWAP executed).
- _flatten_to_usdc is called exactly once (should_flatten()=True for swap).
- run.ending_value == 99_000_000 (post-flatten USDC balance).
- At least one execute event with a non-empty tx_signature was persisted.
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import select

from src.db.models import Run, RunEvent
from src.db.schemas import AgentAction, AgentActionType
from src.services.runner_service import RunnerService
from src.providers.hosted_instance_provider import HostedInstanceProvider
from src.runtime.base import InstanceHandle
from tests._rebalance_helpers import (
    make_swap_instance,
    make_completed_swap_run,
)


_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
_SOL_MINT  = "So11111111111111111111111111111111111111112"
_QUOTE_ID  = "test-quote-001"


def _swap_challenge_row():
    ch = MagicMock()
    ch.config_json = json.dumps({
        "starting_usdc": 100_000_000,
        "swap_intents": [_SOL_MINT],
        "max_slippage_bps": 100,
        "iteration_budget": 20,
        "time_budget_secs": 300,
        "usdc_mint": _USDC_MINT,
    })
    return ch


@pytest.mark.asyncio
async def test_swap_runner_path_unchanged(db):
    """Swap path regression-lock: EXECUTE_SWAP + flatten + ending_value all intact."""
    # --- Setup: seed swap instance + agent in DB ---
    template, instance, agent = await make_swap_instance(db)

    from src.db.models import Challenge
    from src.config import settings
    from datetime import datetime, timezone

    challenge_row = Challenge(
        challenge_type="swap_execution",
        challenge_version=settings.CHALLENGE_VERSION,
        llm_provider="anthropic",
        llm_model="claude-sonnet-4-20250514",
        config_json=_swap_challenge_row().config_json,
        status="active",
        num_contestants=1,
        num_finalized=0,
    )
    db.add(challenge_row)
    await db.flush()

    run = Run(
        challenge_id=challenge_row.challenge_id,
        agent_id=agent.agent_id,
        provider_type="hosted_instance",
        status="pending",
        starting_value=100_000_000,
        app_version=settings.APP_VERSION,
        challenge_type="swap_execution",
        challenge_version=settings.CHALLENGE_VERSION,
        action_schema_version=settings.ACTION_SCHEMA_VERSION,
        evidence_schema_version=settings.EVIDENCE_SCHEMA_VERSION,
        benchmark_wallet_address="<test-wallet-swap>",
        benchmark_wallet_ref="<test-priv-id-swap>",
    )
    db.add(run)
    await db.flush()

    # --- Stub quote ---
    from src.challenges.base import QuoteOption
    from datetime import datetime, timezone as _tz

    quote = MagicMock()
    quote.quote_id = _QUOTE_ID
    quote.input_mint = _USDC_MINT
    quote.output_mint = _SOL_MINT
    quote.in_amount = 100_000_000
    quote.out_amount = 9_000_000
    quote.model_dump = MagicMock(return_value={
        "quote_id": _QUOTE_ID,
        "input_mint": _USDC_MINT,
        "output_mint": _SOL_MINT,
        "in_amount": 100_000_000,
        "out_amount": 9_000_000,
    })

    # --- Stub swap_service ---
    swap_service = MagicMock()
    swap_service.get_quotes = AsyncMock(return_value=[quote])
    swap_service.prepare_swap_transaction = AsyncMock(return_value=b"\x01\x02\x03")
    swap_service.get_cached_quote = MagicMock(return_value=quote)

    # --- Stub wallet_service ---
    # Three balance calls:
    # 1. observe: starting balances
    # 2. _flatten_to_usdc: reads non-USDC balances to flatten
    # 3. _finalize_run: post-flatten ending balance
    balance_sequence = [
        {_USDC_MINT: 100_000_000},            # observe
        {_SOL_MINT: 9_000_000},               # _flatten_to_usdc read
        {_USDC_MINT: 99_000_000},             # _finalize_run read
    ]
    call_count = [0]

    async def _get_balances(addr):
        idx = min(call_count[0], len(balance_sequence) - 1)
        call_count[0] += 1
        return balance_sequence[idx]

    wallet_service = MagicMock()
    wallet_service.get_token_balances = AsyncMock(side_effect=_get_balances)
    wallet_service.sign_and_send_transaction = AsyncMock(return_value="tx_sig_swap_001")

    # --- Provider: [EXECUTE_SWAP, FINISH] ---
    actions = [
        AgentAction(type=AgentActionType.EXECUTE_SWAP, params={
            "quote_id": _QUOTE_ID,
            "max_slippage_bps": 100,
        }),
        AgentAction(type=AgentActionType.FINISH, params={}),
    ]
    action_idx = [0]

    async def _decide(handle, state):
        i = action_idx[0]
        action_idx[0] += 1
        if i < len(actions):
            return actions[i]
        return AgentAction(type=AgentActionType.FINISH, params={})

    runtime = MagicMock()
    runtime.invoke_decide = AsyncMock(side_effect=_decide)
    handle = InstanceHandle(instance_id=str(instance.instance_id))
    provider = HostedInstanceProvider(runtime=runtime, handle=handle)

    # --- Build runner (no program_client) ---
    runner = RunnerService(
        db=db,
        swap_service=swap_service,
        wallet_service=wallet_service,
        program_client=None,
    )

    challenge = _swap_challenge_row()

    # Spy on _flatten_to_usdc to confirm it is called exactly once
    with patch.object(
        RunnerService, "_flatten_to_usdc", wraps=runner._flatten_to_usdc
    ) as flatten_spy:
        result = await runner.execute_run(run, challenge, provider)

    # ---- ASSERTIONS ----

    # 1. prepare_swap_transaction called at least once (EXECUTE_SWAP executed)
    assert swap_service.prepare_swap_transaction.await_count >= 1, (
        "swap_service.prepare_swap_transaction must be called for EXECUTE_SWAP"
    )

    # 2. _flatten_to_usdc called exactly once (swap should_flatten()=True)
    assert flatten_spy.call_count == 1, (
        f"_flatten_to_usdc must be called exactly once for swap; "
        f"got {flatten_spy.call_count}"
    )

    # 3. ending_value is the post-flatten USDC balance
    refreshed = await db.get(Run, run.run_id)
    assert refreshed.ending_value == 99_000_000, (
        f"Expected ending_value=99_000_000, got {refreshed.ending_value}"
    )

    # 4. At least one execute event with a non-empty tx_signature was persisted
    events = (
        await db.execute(
            select(RunEvent).where(RunEvent.run_id == run.run_id)
        )
    ).scalars().all()
    execute_events_with_sig = [
        e for e in events
        if e.event_type == "execute" and e.tx_signature
    ]
    assert len(execute_events_with_sig) >= 1, (
        "At least one execute event with a non-empty tx_signature must be persisted"
    )

# agent-rank/backend/tests/integration/test_rebalance_no_swap_no_flatten.py
"""TDD integration test — rebalance run does NOT call swap or flatten, DOES emit evidence.

Spec §5.4 patch gates verified end-to-end:
- Patch 2: ActionValidator receives allowed_action_types from adapter
  (rebalance only permits FINISH/WAIT, so EXECUTE_SWAP is never called).
- Patch 3: _flatten_to_usdc is NOT called for rebalance (should_flatten()=False).
- Patch 5: emit_run_evidence IS called for rebalance, writing one artifact.

This test is written BEFORE the production patches and must fail RED until
all three patches land in runner_service.py.
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import select

from src.db.models import VerificationArtifact
from src.db.schemas import AgentAction, AgentActionType
from src.services.runner_service import RunnerService
from src.providers.hosted_instance_provider import HostedInstanceProvider
from src.runtime.base import InstanceHandle
from tests._rebalance_helpers import (
    make_rebalance_instance,
    make_completed_rebalance_run,
)


_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
_SOL_MINT  = "So11111111111111111111111111111111111111112"


def _rebalance_challenge_row():
    """Minimal challenge mock for a rebalance_execution run."""
    ch = MagicMock()
    ch.config_json = json.dumps({
        "starting_usdc": 100_000_000,
        "allowed_token_universe": [_SOL_MINT, _USDC_MINT],
        "target_allocations": {
            _SOL_MINT:  0.6,
            _USDC_MINT: 0.4,
        },
        "rebalance_threshold_bps": 50,
        "max_slippage_bps": 100,
        "max_position_weight": 0.7,
        "max_trade_value": 1_000_000_000,
        "dry_run": True,
        "iteration_budget": 5,
        "time_budget_secs": 60,
    })
    return ch


@pytest.mark.asyncio
async def test_rebalance_no_swap_no_flatten(db):
    """Full runner path for rebalance_execution:
    - swap_service.prepare_swap_transaction MUST NOT be called.
    - swap_service.sign_and_send_transaction MUST NOT be called.
    - No RunEvent with event_type='flatten' should be persisted.
    - Exactly one rebalance_evidence_v1 VerificationArtifact must be written.
    """
    # --- Setup: seed rebalance instance + agent in DB ---
    template, instance, agent = await make_rebalance_instance(db)

    # Build a real Run row (pending state) directly — RunnerService mutates it in place.
    from src.db.models import Challenge, Run
    from src.config import settings
    from datetime import datetime, timezone

    challenge_row = await db.execute(
        select(Challenge).where(Challenge.challenge_type == "rebalance_execution")
    )
    challenge_row = challenge_row.scalar_one_or_none()
    if challenge_row is None:
        # Seed a challenge row so run FK is valid
        challenge_row = Challenge(
            challenge_type="rebalance_execution",
            challenge_version="rebalance_execution_v1",
            llm_provider="anthropic",
            llm_model="claude-sonnet-4-20250514",
            config_json=_rebalance_challenge_row().config_json,
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
        challenge_type="rebalance_execution",
        challenge_version="rebalance_execution_v1",
        action_schema_version=settings.ACTION_SCHEMA_VERSION,
        evidence_schema_version=settings.EVIDENCE_SCHEMA_VERSION,
        benchmark_wallet_address="<test-wallet-rebalance>",
        benchmark_wallet_ref="<test-priv-id-rebalance>",
    )
    db.add(run)
    await db.flush()

    # --- Stub swap_service ---
    swap_service = AsyncMock()
    swap_service.prepare_swap_transaction = AsyncMock(
        side_effect=AssertionError("prepare_swap_transaction must not be called for rebalance")
    )
    swap_service.get_cached_quote = MagicMock(return_value=None)
    swap_service.get_quotes = AsyncMock(return_value=[])

    # --- Stub wallet_service ---
    wallet_service = AsyncMock()
    wallet_service.get_token_balances = AsyncMock(
        return_value={_USDC_MINT: 100_000_000}
    )
    wallet_service.sign_and_send_transaction = AsyncMock(
        side_effect=AssertionError("sign_and_send_transaction must not be called for rebalance")
    )

    # --- Build provider: runtime returns FINISH immediately ---
    finish_action = AgentAction(type=AgentActionType.FINISH, params={})
    runtime = AsyncMock()
    runtime.invoke_decide = AsyncMock(return_value=finish_action)
    handle = InstanceHandle(instance_id=str(instance.instance_id))
    provider = HostedInstanceProvider(runtime=runtime, handle=handle)

    # --- Build runner (no program_client — avoids on-chain call) ---
    runner = RunnerService(
        db=db,
        swap_service=swap_service,
        wallet_service=wallet_service,
        program_client=None,
    )

    challenge = _rebalance_challenge_row()

    # --- Execute ---
    result = await runner.execute_run(run, challenge, provider)

    # ---- ASSERTIONS ----

    # 1. Swap and sign-and-send were NOT called
    swap_service.prepare_swap_transaction.assert_not_called()
    wallet_service.sign_and_send_transaction.assert_not_called()

    # 2. No 'flatten' event in the in-memory events — we query RunEvent rows
    from src.db.models import RunEvent
    events = (
        await db.execute(
            select(RunEvent).where(RunEvent.run_id == run.run_id)
        )
    ).scalars().all()
    event_types = [e.event_type for e in events]
    assert "flatten" not in event_types, (
        f"flatten event must NOT be emitted for rebalance; got {event_types}"
    )

    # 3. Exactly one rebalance_evidence_v1 artifact was written
    artifacts = (
        await db.execute(
            select(VerificationArtifact).where(
                VerificationArtifact.run_id == run.run_id,
                VerificationArtifact.artifact_type == "rebalance_evidence_v1",
            )
        )
    ).scalars().all()
    assert len(artifacts) == 1, (
        f"Expected exactly 1 rebalance_evidence_v1 artifact, got {len(artifacts)}"
    )

    # 4. Run status is completed
    assert result.status == "completed"

"""Spec §10 test 5 — swap adapter implements 4 hooks with V1-preserving behavior.

Task 9 lands this file. Task 12 appends additional dispatch tests later;
this file's per-task ownership is marker-commented for clarity.
"""
from __future__ import annotations

import pytest

from src.challenges.swap_execution import SwapExecutionChallenge
from src.db.schemas import AgentActionType


def _make_swap_adapter():
    return SwapExecutionChallenge({
        "starting_usdc": 100_000_000,
        "swap_intents": ["SOL"],
        "allowed_routes": [["USDC", "SOL"]],
        "iteration_budget": 20,
        "time_budget_secs": 300,
        "max_slippage_bps": 100,
        "usdc_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    })


def test_swap_allowed_action_types_is_full_set():
    adapter = _make_swap_adapter()
    assert adapter.allowed_action_types() == {
        AgentActionType.EXECUTE_SWAP,
        AgentActionType.WAIT,
        AgentActionType.FINISH,
    }


def test_swap_should_flatten_returns_true():
    adapter = _make_swap_adapter()
    assert adapter.should_flatten() is True


def test_swap_compute_ending_value_equivalent_to_v1_inline_lookup():
    """Regression-lock equivalence: must match the V1 inline computation.

    V1 runner computed `final_balances.get(adapter.usdc_mint, 0)` inline.
    The new compute_ending_value(run, final_balances) hook must return the
    identical value. Production code change to usdc_mint semantics is
    forbidden — if this fails on first run, halt under the regression-lock
    gate and investigate before touching production code.
    """
    adapter = _make_swap_adapter()
    final_balances = {
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 99_500_000,
        "So11111111111111111111111111111111111111112":          0,
    }
    expected = final_balances.get(adapter.usdc_mint, 0)
    actual = adapter.compute_ending_value(run=object(), final_balances=final_balances)
    assert actual == expected


@pytest.mark.asyncio
async def test_swap_emit_run_evidence_is_no_op():
    adapter = _make_swap_adapter()
    # No-op — must not raise, must not create any artifact, must not write to DB.
    await adapter.emit_run_evidence(db=None, run=None, events=[])

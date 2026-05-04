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


# ---------------------------------------------------------------------------
# Task 12 — runner CHALLENGE_ADAPTERS dispatch + UnknownChallengeTypeError
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock, MagicMock

from src.services.runner_service import (
    CHALLENGE_ADAPTERS,
    RunnerService,
    UnknownChallengeTypeError,
)


def test_challenge_adapters_dict_has_swap_key():
    """Task 12 establishes the dispatch shape with swap_execution.

    Task 13 will extend this test to also assert "rebalance_execution" in
    CHALLENGE_ADAPTERS once the rebalance class exists. At Task 12 time, the
    conditional spread for rebalance_execution evaluates to empty because
    RebalanceExecutionChallenge is None (ImportError fallback). See
    .taskmaster/docs/rebalance-task12-edge-case-spec.md INV-D4.
    """
    assert "swap_execution" in CHALLENGE_ADAPTERS
    assert CHALLENGE_ADAPTERS["swap_execution"] is SwapExecutionChallenge
    # Task 13 will add: assert "rebalance_execution" in CHALLENGE_ADAPTERS


@pytest.mark.asyncio
async def test_unknown_challenge_type_raises_typed_error():
    """INV-D1: unknown challenge_type raises UnknownChallengeTypeError before adapter construction."""
    runner = RunnerService(
        db=AsyncMock(), swap_service=MagicMock(), wallet_service=MagicMock()
    )
    run = MagicMock(challenge_type="completely_unknown")
    challenge = MagicMock(config_json='{"starting_usdc": 0}')
    provider = AsyncMock()
    with pytest.raises(UnknownChallengeTypeError) as exc:
        await runner.execute_run(run, challenge, provider)
    assert "completely_unknown" in str(exc.value)


@pytest.mark.asyncio
async def test_swap_dispatch_constructs_swap_adapter(monkeypatch):
    """Regression-lock: swap_execution still routes to SwapExecutionChallenge."""
    runner = RunnerService(
        db=AsyncMock(), swap_service=MagicMock(), wallet_service=MagicMock()
    )
    run = MagicMock(
        challenge_type="swap_execution",
        benchmark_wallet_address="W",
        benchmark_wallet_ref="R",
    )
    challenge = MagicMock(
        config_json='{"starting_usdc": 100, "swap_intents": [], '
        '"allowed_routes": [], "iteration_budget": 1, '
        '"time_budget_secs": 1, "max_slippage_bps": 100, '
        '"usdc_mint": "U"}'
    )
    provider = AsyncMock()
    captured = {}
    original = CHALLENGE_ADAPTERS["swap_execution"]

    def _spy(cfg):
        captured["cls"] = original
        return original(cfg)

    monkeypatch.setitem(CHALLENGE_ADAPTERS, "swap_execution", _spy)

    # Runner will fail later (mocks aren't fully wired); we only care that
    # dispatch picked SwapExecutionChallenge.
    with pytest.raises(Exception):
        await runner.execute_run(run, challenge, provider)
    assert captured["cls"] is SwapExecutionChallenge

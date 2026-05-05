# tests/integration/test_rebalance_evidence_null_prices.py
"""Defect 2 (HIGH) regression test — null price contract for missing prices.

Verifies that when emit_run_evidence is called with events=[] (no observe event),
the prices_used field in the artifact contains None (null) for every mint in
target_allocations | start_portfolio — NOT the synthetic 1_000_000 fallback.

Spec §5.5 line 193: prices_used: dict[str, int] (mint → integer base-unit price
  snapshot; null entries flag missing prices).
Spec §5.6 line 211: price_data_present_check — passes iff every mint that appears
  in target_allocations or start_portfolio has a non-null value in prices_used.

The synthetic 1_000_000 fallback silently masks missing prices and defeats the
Cat-layer price_data_present_check (Task 20).

This test FAILS before Fix 2 (synthetic fill → 1_000_000 detected).
It PASSES after Fix 2 (missing prices → None).
"""
from __future__ import annotations

import json
import pytest
from sqlalchemy import select

from src.db.models import VerificationArtifact
from src.challenges.rebalance_execution import RebalanceExecutionChallenge
from tests._rebalance_helpers import (
    make_rebalance_envelope,
    make_completed_rebalance_run,
    make_rebalance_instance,
)


@pytest.mark.asyncio
async def test_missing_prices_emit_as_null_not_synthetic_fallback(db):
    """prices_used must contain None for every mint when no observe event provides prices.

    With events=[], no real price data is present. The adapter must emit
    prices_used = {mint: None, ...} per spec §5.5/§5.6, NOT {mint: 1_000_000, ...}.
    The Cat-layer price_data_present_check relies on None to signal missing data.
    """
    template, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=False,
    )

    cfg = make_rebalance_envelope()
    cfg["starting_usdc"] = 100_000_000
    adapter = RebalanceExecutionChallenge(cfg)

    # No events → no observe snapshot → prices_used should be all-None
    await adapter.emit_run_evidence(db, run, events=[])

    artifact = (
        await db.execute(
            select(VerificationArtifact).where(
                VerificationArtifact.run_id == run.run_id,
                VerificationArtifact.artifact_type == "rebalance_evidence_v1",
            )
        )
    ).scalar_one()

    payload = json.loads(artifact.uri_or_ref)
    prices_used = payload["prices_used"]
    target_allocs = set(payload["target_allocations"].keys())
    start_portfolio = set(payload["start_portfolio"].keys())
    mints_in_scope = target_allocs | start_portfolio

    # Every in-scope mint must have a None (null) entry — not 1_000_000
    for mint in mints_in_scope:
        assert mint in prices_used, (
            f"Mint {mint!r} missing from prices_used entirely (must be present as null)"
        )
        assert prices_used[mint] is None, (
            f"prices_used[{mint!r}] = {prices_used[mint]!r}, expected None. "
            "The synthetic 1_000_000 fallback must be removed per spec §5.5/§5.6. "
            "Missing prices must appear as null to trigger price_data_present_check."
        )

    # Belt-and-suspenders: confirm the synthetic sentinel is not present anywhere
    synthetic_fill = 1_000_000
    for mint, price in prices_used.items():
        assert price != synthetic_fill, (
            f"prices_used[{mint!r}] = {synthetic_fill} (synthetic fill detected). "
            "Must be None for missing prices."
        )


@pytest.mark.asyncio
async def test_universe_only_mint_not_in_target_still_gets_null_price(db):
    """Round-2 regression: every mint in final start_portfolio gets a prices_used entry.

    Spec §5.6 requires "every mint that appears in target_allocations or
    start_portfolio has a non-null value in prices_used". The previous fix
    computed mints_in_scope BEFORE filling start_portfolio with
    allowed_token_universe zero-balances, so mints that were in
    allowed_token_universe but NOT in target_allocations got balance=0 in
    start_portfolio without a corresponding prices_used[mint]=None entry.

    This test pins the contract: when target_allocations is a strict subset of
    allowed_token_universe, the universe-only mint must still appear in
    prices_used as None (so the Cat-layer price_data_present_check fails on
    missing data, not on missing-key).
    """
    template, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=False,
    )

    # Envelope: USDT is allowed but not in target_allocations.
    SOL = "So11111111111111111111111111111111111111112"
    USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
    cfg = make_rebalance_envelope(
        allowed_token_universe=[SOL, USDC, USDT],
        target_allocations={SOL: 0.5, USDC: 0.5},  # USDT allowed but not targeted
    )
    cfg["starting_usdc"] = 100_000_000
    adapter = RebalanceExecutionChallenge(cfg)

    await adapter.emit_run_evidence(db, run, events=[])

    artifact = (
        await db.execute(
            select(VerificationArtifact).where(
                VerificationArtifact.run_id == run.run_id,
                VerificationArtifact.artifact_type == "rebalance_evidence_v1",
            )
        )
    ).scalar_one()

    payload = json.loads(artifact.uri_or_ref)
    prices_used = payload["prices_used"]
    start_portfolio = payload["start_portfolio"]

    # USDT is in allowed_token_universe → goes into start_portfolio with balance 0.
    # It MUST also appear in prices_used as None (final-start_portfolio scope).
    assert USDT in start_portfolio, (
        f"USDT must appear in start_portfolio after universe-zero fill; got keys "
        f"{list(start_portfolio.keys())!r}"
    )
    assert start_portfolio[USDT] == 0, (
        f"USDT balance must be 0 (universe-zero fill); got {start_portfolio[USDT]!r}"
    )
    assert USDT in prices_used, (
        f"USDT in start_portfolio but MISSING from prices_used. Spec §5.6 requires "
        f"every mint in target_allocations | start_portfolio to have an entry in "
        f"prices_used (null for missing prices). Got prices_used keys "
        f"{sorted(prices_used.keys())!r}, start_portfolio keys "
        f"{sorted(start_portfolio.keys())!r}."
    )
    assert prices_used[USDT] is None, (
        f"prices_used[USDT] must be None (missing-price signal); got {prices_used[USDT]!r}"
    )

    # All 3 universe mints must have explicit None entries.
    for mint in (SOL, USDC, USDT):
        assert mint in prices_used, f"{mint!r} missing from prices_used"
        assert prices_used[mint] is None, (
            f"prices_used[{mint!r}] = {prices_used[mint]!r}, expected None"
        )

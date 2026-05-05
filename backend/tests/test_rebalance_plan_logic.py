"""V0 deterministic rebalance plan computation (spec §5.5)."""
from __future__ import annotations

from src.challenges.rebalance_execution import RebalanceExecutionChallenge
from tests._rebalance_helpers import make_rebalance_envelope


def _adapter(**overrides):
    cfg = make_rebalance_envelope(**overrides)
    cfg["starting_usdc"] = 100_000_000
    return RebalanceExecutionChallenge(cfg)


def test_plan_legs_status_is_planned_in_v0():
    adapter = _adapter()
    plan = adapter._compute_v0_plan(
        start_portfolio={
            "So11111111111111111111111111111111111111112":  10_000_000,
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 10_000_000,
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB":          0,
        },
        prices_used={
            "So11111111111111111111111111111111111111112":  100_000_000,
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v":   1_000_000,
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB":   1_000_000,
        },
    )
    assert all(leg["status"] == "planned" for leg in plan["legs"])
    assert all(leg["slippage_bps_realized"] == 0 for leg in plan["legs"])


def test_plan_drift_pre_run_is_computed_from_start_portfolio():
    adapter = _adapter()
    plan = adapter._compute_v0_plan(
        start_portfolio={
            "So11111111111111111111111111111111111111112":  20_000_000,
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 30_000_000,
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB":  20_000_000,
        },
        prices_used={
            "So11111111111111111111111111111111111111112":  10_000_000,
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v":   1_000_000,
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB":   1_000_000,
        },
    )
    assert plan["summary"]["drift_bps_pre_run"] >= 0
    assert plan["summary"]["drift_bps_post_run"] == plan["summary"]["drift_bps_pre_run"]


def test_plan_legs_subset_of_allowed_universe():
    adapter = _adapter()
    plan = adapter._compute_v0_plan(
        start_portfolio={"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 100_000_000},
        prices_used={
            "So11111111111111111111111111111111111111112":  10_000_000,
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v":  1_000_000,
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB":  1_000_000,
        },
    )
    universe = set(adapter.allowed_token_universe)
    assert all(leg["mint"] in universe for leg in plan["legs"])


def test_plan_skips_zero_drift():
    """If start portfolio is already at target (drift < threshold), plan has zero legs."""
    adapter = _adapter(rebalance_threshold_bps=100, target_allocations={
        "So11111111111111111111111111111111111111112":  0.5,
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 0.5,
    })
    plan = adapter._compute_v0_plan(
        start_portfolio={
            "So11111111111111111111111111111111111111112":   500_000,
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 50_000_000,
        },
        prices_used={
            "So11111111111111111111111111111111111111112": 100_000_000,
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v":   1_000_000,
        },
    )
    assert plan["legs"] == [] or all(leg["size_base_units"] == 0 for leg in plan["legs"])


def test_plan_handles_missing_price_gracefully():
    adapter = _adapter()
    plan = adapter._compute_v0_plan(
        start_portfolio={
            "So11111111111111111111111111111111111111112":  10_000_000,
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 10_000_000,
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB":          0,
        },
        prices_used={
            "So11111111111111111111111111111111111111112":  None,
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 1_000_000,
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": 1_000_000,
        },
    )
    assert "legs" in plan
    assert "prices_used" in plan
    assert plan["prices_used"]["So11111111111111111111111111111111111111112"] is None

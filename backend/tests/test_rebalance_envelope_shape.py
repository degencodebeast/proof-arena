"""Spec §10 test 2 — rebalance envelope range/integrity checks (Task 3)."""
from __future__ import annotations

from src.policy.engine import validate_spec_for_template
from tests._rebalance_helpers import make_rebalance_envelope


def test_target_allocations_sum_within_tolerance():
    """INV-1: sum(target_allocations.values()) must be 1.0 ± 0.01 (closed)."""
    spec = make_rebalance_envelope(target_allocations={
        "So11111111111111111111111111111111111111112":  0.6,
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 0.6,  # sum = 1.2
    })
    result = validate_spec_for_template("rebalance_executor_v1", spec)
    assert not result.ok
    assert any("sum" in e.lower() and "target_allocations" in e for e in result.errors)


def test_target_allocations_keys_must_subset_universe():
    """INV-2: every target_allocations key must be in allowed_token_universe."""
    spec = make_rebalance_envelope(target_allocations={
        "So11111111111111111111111111111111111111112":  1.0,
        "MintNotInUniverse111111111111111111111111111": 0.0,  # not in universe
    })
    result = validate_spec_for_template("rebalance_executor_v1", spec)
    assert not result.ok
    assert any("allowed_token_universe" in e for e in result.errors)


def test_rebalance_threshold_bps_out_of_range():
    """INV-3: rebalance_threshold_bps must be int in [1, 5000]."""
    spec = make_rebalance_envelope(rebalance_threshold_bps=0)
    assert not validate_spec_for_template("rebalance_executor_v1", spec).ok
    spec2 = make_rebalance_envelope(rebalance_threshold_bps=5001)
    assert not validate_spec_for_template("rebalance_executor_v1", spec2).ok


def test_max_position_weight_out_of_range():
    """INV-4: max_position_weight must be in (0.0, 1.0] (exclusive lower, inclusive upper)."""
    spec = make_rebalance_envelope(max_position_weight=0.0)  # exclusive lower
    assert not validate_spec_for_template("rebalance_executor_v1", spec).ok
    spec2 = make_rebalance_envelope(max_position_weight=1.5)
    assert not validate_spec_for_template("rebalance_executor_v1", spec2).ok


def test_max_slippage_bps_out_of_range():
    """INV-5: max_slippage_bps must be int in [0, 500]."""
    spec = make_rebalance_envelope(max_slippage_bps=-1)
    assert not validate_spec_for_template("rebalance_executor_v1", spec).ok
    spec2 = make_rebalance_envelope(max_slippage_bps=501)
    assert not validate_spec_for_template("rebalance_executor_v1", spec2).ok


def test_max_trade_value_must_be_positive():
    """INV-6: max_trade_value must be int >= 1."""
    spec = make_rebalance_envelope(max_trade_value=0)
    assert not validate_spec_for_template("rebalance_executor_v1", spec).ok


def test_dry_run_must_be_bool():
    """INV-7: dry_run must be strict bool (1/0/None rejected)."""
    spec = make_rebalance_envelope(dry_run=1)  # int, not bool
    assert not validate_spec_for_template("rebalance_executor_v1", spec).ok


def test_empty_allowed_token_universe_rejected():
    """INV-8: allowed_token_universe must be non-empty."""
    spec = make_rebalance_envelope(allowed_token_universe=[])
    assert not validate_spec_for_template("rebalance_executor_v1", spec).ok


def test_negative_target_allocation_value_rejected():
    """INV-9: negative target_allocations values are invalid."""
    spec = make_rebalance_envelope(target_allocations={
        "So11111111111111111111111111111111111111112":  -0.1,
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v":  1.1,
    })
    assert not validate_spec_for_template("rebalance_executor_v1", spec).ok


def test_empty_target_allocations_rejected():
    """INV-10: target_allocations must be non-empty."""
    spec = make_rebalance_envelope(target_allocations={})
    assert not validate_spec_for_template("rebalance_executor_v1", spec).ok


def test_zero_target_allocation_value_accepted():
    """INV-11: zero-weight target_allocations entries ARE allowed (skip-in-plan).

    Per spec §5.1: target_allocations values in [0.0, 1.0] (both endpoints included).
    Sum-tolerance still applies, so the non-zero entries must sum to 1.0 ± 0.01.
    """
    spec = make_rebalance_envelope(target_allocations={
        "So11111111111111111111111111111111111111112":  0.5,
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 0.5,
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": 0.0,
    })
    result = validate_spec_for_template("rebalance_executor_v1", spec)
    assert result.ok, f"zero-weight allocations must be accepted; errors: {result.errors}"


def test_target_allocations_sum_at_lower_closed_boundary_accepted():
    """Spec §5.1 closed interval: sum exactly 0.99 must be ACCEPTED.

    Bug: naive `abs(total - 1.0) > 0.01` rejects 0.99 due to float drift
    (0.49 + 0.50 + 0.0 = 0.9899999999999999, abs delta ≈ 0.010000000000000009 > 0.01).
    """
    spec = make_rebalance_envelope(target_allocations={
        "So11111111111111111111111111111111111111112":  0.49,
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 0.50,
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": 0.0,
    })
    result = validate_spec_for_template("rebalance_executor_v1", spec)
    assert result.ok, (
        f"sum=0.99 must be accepted (closed interval per spec §5.1); "
        f"errors: {result.errors}"
    )


def test_target_allocations_sum_at_upper_closed_boundary_accepted():
    """Spec §5.1 closed interval: sum exactly 1.01 must be ACCEPTED."""
    spec = make_rebalance_envelope(target_allocations={
        "So11111111111111111111111111111111111111112":  0.51,
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 0.50,
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": 0.0,
    })
    result = validate_spec_for_template("rebalance_executor_v1", spec)
    assert result.ok, (
        f"sum=1.01 must be accepted (closed interval per spec §5.1); "
        f"errors: {result.errors}"
    )


def test_target_allocations_sum_just_below_lower_boundary_rejected():
    """Spec §5.1: sum=0.98 is OUTSIDE the closed interval and must be REJECTED."""
    spec = make_rebalance_envelope(target_allocations={
        "So11111111111111111111111111111111111111112":  0.48,
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 0.50,
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": 0.0,
    })
    result = validate_spec_for_template("rebalance_executor_v1", spec)
    assert not result.ok
    assert any("sum" in e.lower() and "1.0" in e for e in result.errors)


def test_target_allocations_sum_just_above_upper_boundary_rejected():
    """Spec §5.1: sum=1.02 is OUTSIDE the closed interval and must be REJECTED."""
    spec = make_rebalance_envelope(target_allocations={
        "So11111111111111111111111111111111111111112":  0.52,
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 0.50,
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": 0.0,
    })
    result = validate_spec_for_template("rebalance_executor_v1", spec)
    assert not result.ok
    assert any("sum" in e.lower() and "1.0" in e for e in result.errors)

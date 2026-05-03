"""Local test helpers for rebalance executor V0 tests.

These helpers provide:
- Baseline envelope factories (make_rebalance_envelope, make_swap_envelope)
- Canonical evidence JSON/hash helpers
- Evidence payload builder
- Private-field leakage assertion
- Stub async DB helpers for later tasks (Task 9, 15, 16)
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


# ---------------------------------------------------------------------------
# Baseline envelope factories
# ---------------------------------------------------------------------------

def make_rebalance_envelope(**overrides) -> dict[str, Any]:
    """Return the V0 baseline rebalance envelope merged with overrides."""
    base: dict[str, Any] = {
        "allowed_token_universe": [
            "So11111111111111111111111111111111111111112",
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
        ],
        "target_allocations": {
            "So11111111111111111111111111111111111111112": 0.5,
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 0.3,
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": 0.2,
        },
        "rebalance_threshold_bps": 50,
        "max_slippage_bps": 100,
        "max_position_weight": 0.7,
        "max_trade_value": 1_000_000_000,
        "dry_run": True,
    }
    base.update(overrides)
    return base


def make_swap_envelope(**overrides) -> dict[str, Any]:
    """Return the V2 5-field swap envelope baseline.

    Values are chosen to pass validate_spec().
    """
    base: dict[str, Any] = {
        "allowed_token_universe": [
            "So11111111111111111111111111111111111111112",
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        ],
        "max_slippage_bps": 100,
        "max_position_size": 1_000_000,
        "max_iterations": 20,
        "max_runtime_seconds": 300,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Canonical evidence JSON / hash helpers
# ---------------------------------------------------------------------------

def canonical_rebalance_evidence_json(payload: dict) -> tuple[str, str]:
    """Return (canonical_json, sha256_hexdigest) for an evidence payload.

    Uses the same recipe as policy.engine.record_consent:
    json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    then sha256.hexdigest().
    """
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return canonical, digest


# ---------------------------------------------------------------------------
# Evidence payload builder
# ---------------------------------------------------------------------------

_SOL_MINT = "So11111111111111111111111111111111111111112"
_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
_USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

_DEFAULT_PRICES: dict[str, int] = {
    _SOL_MINT: 1_000_000,
    _USDC_MINT: 1_000_000,
    _USDT_MINT: 1_000_000,
}

_DEFAULT_START_PORTFOLIO: dict[str, int] = {
    _SOL_MINT: 500_000,
    _USDC_MINT: 300_000,
    _USDT_MINT: 200_000,
}


def make_rebalance_evidence_payload(
    *,
    run_id: int,
    instance_id: int,
    envelope: dict,
    prices_used: dict[str, int] | None = None,
    start_portfolio: dict[str, int] | None = None,
    end_portfolio: dict[str, int] | None = None,
    legs: list[dict] | None = None,
    summary: dict | None = None,
) -> dict:
    """Build the canonical-shape rebalance_evidence_v1 payload per spec §5.5.

    V0-locked defaults:
    - Every leg status="planned", slippage_bps_realized=0
    - Prices = synthetic 1_000_000 base-units when omitted
    - end_portfolio == start_portfolio (dry-run, no execution)
    """
    if prices_used is None:
        prices_used = dict(_DEFAULT_PRICES)

    if start_portfolio is None:
        start_portfolio = dict(_DEFAULT_START_PORTFOLIO)

    if end_portfolio is None:
        end_portfolio = dict(start_portfolio)

    if legs is None:
        target_allocs = envelope.get("target_allocations", {})
        legs = [
            {
                "mint": mint,
                "side": "BUY",
                "size_base_units": 0,
                "slippage_bps_realized": 0,
                "status": "planned",
            }
            for mint in target_allocs
        ]

    if summary is None:
        summary = {
            "drift_bps_pre_run": 0,
            "drift_bps_post_run": 0,
            "total_traded_value_base_units": 0,
            "max_leg_slippage_bps": 0,
        }

    return {
        "evidence_schema_version": "rebalance_evidence_v1",
        "run_id": run_id,
        "instance_id": instance_id,
        "template_key": "rebalance_executor_v1",
        "effective_envelope": envelope,
        "target_allocations": envelope.get("target_allocations", {}),
        "prices_used": prices_used,
        "start_portfolio": start_portfolio,
        "end_portfolio": end_portfolio,
        "legs": legs,
        "dry_run": envelope.get("dry_run", True),
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Private-field leakage assertion
# ---------------------------------------------------------------------------

_PRIVATE_FIELD_NAMES = frozenset({
    "uri_or_ref",
    "wallet_address",
    "hosted_wallet_ref",
    "instance_owner_ref",
    "runtime_handle_json",
    "system_prompt",
    "config_json",
})


def assert_no_private_field_leakage(
    serialized_response: dict,
    fixture_values: list[str],
) -> None:
    """Assert that serialized_response does not leak private fields.

    Checks:
    - json.dumps(serialized_response) does NOT contain any of the private field
      name strings as substrings.
    - json.dumps(serialized_response) does NOT contain any of the fixture_values
      strings as substrings.
    """
    dumped = json.dumps(serialized_response)
    for field_name in _PRIVATE_FIELD_NAMES:
        assert field_name not in dumped, (
            f"Private field {field_name!r} leaked in serialized response"
        )
    for value in fixture_values:
        assert value not in dumped, (
            f"Fixture value {value!r} leaked in serialized response"
        )


# ---------------------------------------------------------------------------
# Stub async helpers for later tasks
# ---------------------------------------------------------------------------

async def make_rebalance_instance(
    db,
    *,
    owner_ref: str = "instance:9001",
    trust_label: str = "benchmark_compatible_customized_instance",
    template_key: str = "rebalance_executor_v1",
    effective_config: dict | None = None,
    **kwargs,
):
    """Stub: creates a rebalance AgentInstance row in the test DB.

    Task 16 fills this in.
    """
    raise NotImplementedError(
        "make_rebalance_instance is a stub — Task 16 implements it. "
        "Do not call before Task 16 is complete."
    )


async def make_completed_rebalance_run(
    db,
    *,
    agent,
    instance,
    completion_status: str = "complete",
    invalid_reason: str | None = None,
    with_evidence: bool = True,
    evidence_overrides: dict | None = None,
    **kwargs,
):
    """Stub: creates a completed rebalance Run + optional evidence artifact.

    Task 15 fills this in.
    """
    raise NotImplementedError(
        "make_completed_rebalance_run is a stub — Task 15 implements it. "
        "Do not call before Task 15 is complete."
    )


async def make_completed_swap_run(
    db,
    *,
    agent,
    instance,
    completion_status: str = "complete",
    invalid_reason: str | None = None,
    **kwargs,
):
    """Stub: creates a completed swap Run row in the test DB.

    Task 9 fills this in.
    """
    raise NotImplementedError(
        "make_completed_swap_run is a stub — Task 9 implements it. "
        "Do not call before Task 9 is complete."
    )


async def make_swap_instance(
    db,
    *,
    owner_ref: str = "instance:9000",
    trust_label: str = "benchmark_compatible_customized_instance",
    **kwargs,
):
    """Stub: creates a swap AgentInstance row in the test DB.

    Task 9 fills this in.
    """
    raise NotImplementedError(
        "make_swap_instance is a stub — Task 9 implements it. "
        "Do not call before Task 9 is complete."
    )

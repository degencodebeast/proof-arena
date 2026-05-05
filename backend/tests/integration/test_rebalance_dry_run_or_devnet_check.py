"""Spec §10 test 18 — three synthetic predicate cases for dry_run_or_devnet_check."""
import pytest
from src.integrity.cats.rebalance_policy import compute_rebalance_policy_cat
from tests._rebalance_helpers import (
    make_completed_rebalance_run,
    make_rebalance_envelope,
    make_rebalance_instance,
)


@pytest.mark.asyncio
async def test_case_a_dry_run_false_fails(db):
    template, instance, agent = await make_rebalance_instance(
        db, effective_config=make_rebalance_envelope(dry_run=False),
    )
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
        evidence_overrides={
            "effective_envelope": make_rebalance_envelope(dry_run=False),
            "legs": [],
        },
    )
    response = await compute_rebalance_policy_cat(db, run.run_id)
    assert response.result == "fail"
    failing = {c.check_id for c in response.checks if c.result == "fail"}
    assert "dry_run_or_devnet_check" in failing


@pytest.mark.asyncio
async def test_case_b_executed_leg_fails(db):
    template, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
        evidence_overrides={"legs": [{"mint": "X", "side": "BUY",
                                       "size_base_units": 1, "slippage_bps_realized": 0,
                                       "status": "executed"}]},
    )
    response = await compute_rebalance_policy_cat(db, run.run_id)
    failing = {c.check_id for c in response.checks if c.result == "fail"}
    assert "dry_run_or_devnet_check" in failing


@pytest.mark.asyncio
async def test_case_c_v0_happy_path_passes(db):
    """Regression-lock: dry_run=True + all legs planned + provider_type=hosted_instance."""
    template, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
        # drift=0 < threshold=50 → no legs, so threshold consistency holds
        evidence_overrides={"legs": []},
    )
    response = await compute_rebalance_policy_cat(db, run.run_id)
    failing = {c.check_id for c in response.checks if c.result == "fail"}
    assert "dry_run_or_devnet_check" not in failing
    assert response.result == "pass"

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
    """Case A: deployed envelope has dry_run=False → clause 1 fails.

    Per spec §5.6 line 216 clause 1, the trust source for `dry_run` is the
    deployed `instance.effective_config_json`. The artifact's
    `effective_envelope.dry_run` is an echo (§5.5 line 192), not authoritative.
    Round-5 cleanup: removed the redundant `evidence_overrides={"effective_envelope": ...}`
    that previously echoed the deployed dry_run=False into the artifact — it
    was dead code post-Round-2 (Cat ignores artifact's effective_envelope).
    """
    template, instance, agent = await make_rebalance_instance(
        db, effective_config=make_rebalance_envelope(dry_run=False),
    )
    # `legs=[]` keeps the rebalance_threshold_check's drift/legs consistency
    # passing (drift=0 < deployed threshold=50, no-legs path holds), so the
    # only check that fails here is dry_run_or_devnet_check on its clause 1.
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
        evidence_overrides={"legs": []},
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

"""Rebalance Policy Cat — integration tests (Task 19 skeleton).

Covers:
  - UnsupportedTemplateError for non-rebalance template runs (test 1)
  - Happy-path all-pass when evidence artifact is present and hash matches (test 2)
  - Stub fails rebalance_evidence_present_check when artifact absent (test 3)
  - Stub fails rebalance_evidence_present_check when content_hash mismatch (test 4)

Spec: §5.6 / §9.
"""
from __future__ import annotations

import hashlib
import json
import pytest

from tests._rebalance_helpers import (
    assert_no_private_field_leakage,
    canonical_rebalance_evidence_json,
    make_completed_rebalance_run,
    make_completed_swap_run,
    make_rebalance_envelope,
    make_rebalance_evidence_payload,
    make_rebalance_instance,
    make_swap_instance,
)

pytestmark = pytest.mark.integration


# =====================================================================
# Test 1 — UnsupportedTemplateError raised for non-rebalance template
# =====================================================================


async def test_rebalance_policy_cat_raises_unsupported_template_for_swap_run(db):
    """Swap-template run → UnsupportedTemplateError with correct template_key."""
    from src.integrity.cats.rebalance_policy import (
        UnsupportedTemplateError,
        compute_rebalance_policy_cat,
    )

    _tmpl, instance, agent = await make_swap_instance(db)
    run = await make_completed_swap_run(db, agent=agent, instance=instance)
    await db.commit()

    with pytest.raises(UnsupportedTemplateError) as ei:
        await compute_rebalance_policy_cat(db, run.run_id)
    assert ei.value.template_key == "swap_executor_v1"


# =====================================================================
# Test 2 — Happy-path: all 10 checks pass when valid artifact present
# =====================================================================


async def test_rebalance_policy_cat_all_pass_when_valid_artifact_present(db):
    """Rebalance run with valid artifact → result=pass, all 10 checks pass."""
    from src.integrity.cats.rebalance_policy import compute_rebalance_policy_cat

    _tmpl, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
        # drift_bps_pre_run=0 < rebalance_threshold_bps=50 → no legs required for consistency
        evidence_overrides={"legs": []},
    )
    await db.commit()

    resp = await compute_rebalance_policy_cat(db, run.run_id)

    # Plan-required Literal + lifecycle locks (spec §5.6).
    assert resp.cat == "rebalance_policy"
    assert resp.cat_version == "v1"
    assert resp.run_completion_status == "complete"
    assert resp.result == "pass"
    assert resp.reason is None
    assert resp.critique == ""
    assert resp.run_id == run.run_id
    assert resp.instance_id == instance.instance_id
    assert resp.subject_type == "customized_instance"
    assert resp.trust_label == "benchmark_compatible_customized_instance"
    assert len(resp.checks) == 10
    assert all(c.result == "pass" for c in resp.checks)
    # Evidence block carries artifact metadata.
    assert resp.evidence.evidence_artifact_id is not None
    assert resp.evidence.evidence_content_hash is not None
    assert resp.evidence.run_log_hash == run.run_log_hash
    # Privacy: serialised response must not leak private fields.
    assert_no_private_field_leakage(
        resp.model_dump(),
        fixture_values=["<test-wallet-rebalance>", "<test-priv-id-rebalance>"],
    )


# =====================================================================
# Test 3 — rebalance_evidence_present_check fails when artifact absent
# =====================================================================


async def test_rebalance_policy_cat_fails_evidence_check_when_artifact_absent(db):
    """Rebalance run with no evidence artifact → rebalance_evidence_present_check fails."""
    from src.integrity.cats.rebalance_policy import compute_rebalance_policy_cat

    _tmpl, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=False
    )
    await db.commit()

    resp = await compute_rebalance_policy_cat(db, run.run_id)

    assert resp.result == "fail"
    assert resp.reason is None  # never a RunInvalidReason (spec §6 non-goal 6)
    failing_ids = {c.check_id for c in resp.checks if c.result == "fail"}
    # All checks fail when artifact is absent (no data to evaluate downstream checks).
    assert "rebalance_evidence_present_check" in failing_ids
    assert len(failing_ids) == len(resp.checks)
    # Evidence block reflects absent artifact.
    assert resp.evidence.evidence_artifact_id is None
    assert resp.evidence.evidence_content_hash is None


# =====================================================================
# Test 4 — rebalance_evidence_present_check fails on content_hash mismatch
# =====================================================================


async def test_rebalance_policy_cat_fails_evidence_check_on_hash_mismatch(db):
    """Artifact present but content_hash corrupted → rebalance_evidence_present_check fails."""
    from src.db.models import VerificationArtifact
    from src.integrity.cats.rebalance_policy import compute_rebalance_policy_cat

    _tmpl, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True
    )
    await db.commit()

    # Corrupt the stored content_hash so it no longer matches sha256(uri_or_ref).
    from sqlalchemy import select
    artifact = (
        await db.execute(
            select(VerificationArtifact).where(
                VerificationArtifact.run_id == run.run_id,
                VerificationArtifact.artifact_type == "rebalance_evidence_v1",
            )
        )
    ).scalar_one()
    artifact.content_hash = "0" * 64  # deliberately wrong hash
    await db.flush()

    resp = await compute_rebalance_policy_cat(db, run.run_id)

    assert resp.result == "fail"
    assert resp.reason is None  # never a RunInvalidReason
    failing = [c for c in resp.checks if c.result == "fail"]
    assert len(failing) == 1
    assert failing[0].check_id == "rebalance_evidence_present_check"
    # Response must not raise — just a check-level fail.
    assert resp.evidence.evidence_artifact_id == artifact.artifact_id
    # The stored (corrupted) hash is surfaced, not the recomputed one.
    assert resp.evidence.evidence_content_hash == "0" * 64


# =====================================================================
# Task 20 — per-check failing tests (one violation per predicate)
# =====================================================================


@pytest.mark.asyncio
async def test_target_allocation_sum_check_fails_when_deployed_envelope_sum_off(db):
    """Deployed envelope target sums to 0.7 (not 1.0) → target_allocation_sum_check fails.

    Spec §5.6 line 209: sum(effective_envelope.target_allocations.values()) must be
    within 1.0 ± 0.01. Source = deployed instance.effective_config_json.
    Direct insertion via make_rebalance_instance bypasses validate_spec_for_template,
    simulating either a bypass attack or a validator regression.
    """
    from src.integrity.cats.rebalance_policy import compute_rebalance_policy_cat

    _SOL = "So11111111111111111111111111111111111111112"
    _USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    bad_envelope = make_rebalance_envelope(
        target_allocations={_SOL: 0.4, _USDC: 0.3},  # sum 0.7 ≠ 1.0; both still in universe
    )
    _tmpl, instance, agent = await make_rebalance_instance(
        db, effective_config=bad_envelope,
    )
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
    )
    await db.commit()

    response = await compute_rebalance_policy_cat(db, run.run_id)
    assert response.result == "fail"
    failing_ids = {c.check_id for c in response.checks if c.result == "fail"}
    assert "target_allocation_sum_check" in failing_ids


@pytest.mark.asyncio
async def test_allowed_token_universe_check_fails_when_deployed_target_outside_universe(db):
    """Deployed envelope target contains a mint not in allowed_token_universe → check fails.

    Source per spec §5.6 line 210 = deployed envelope (target_allocations.keys() and
    allowed_token_universe both from instance.effective_config_json).
    """
    from src.integrity.cats.rebalance_policy import compute_rebalance_policy_cat

    _SOL = "So11111111111111111111111111111111111111112"
    _USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    _OUTSIDE = "OutsideMint11111111111111111111111111111111"
    bad_envelope = make_rebalance_envelope(
        allowed_token_universe=[_SOL, _USDC],  # universe excludes OUTSIDE
        target_allocations={_SOL: 0.4, _OUTSIDE: 0.6},  # OUTSIDE not in universe
    )
    _tmpl, instance, agent = await make_rebalance_instance(
        db, effective_config=bad_envelope,
    )
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
    )
    await db.commit()

    response = await compute_rebalance_policy_cat(db, run.run_id)
    assert response.result == "fail"
    failing_ids = {c.check_id for c in response.checks if c.result == "fail"}
    assert "allowed_token_universe_check" in failing_ids


@pytest.mark.asyncio
async def test_price_data_present_check_fails_when_price_is_null(db):
    """prices_used has a None entry for a portfolio mint → price_data_present_check fails."""
    from src.integrity.cats.rebalance_policy import compute_rebalance_policy_cat

    _SOL = "So11111111111111111111111111111111111111112"
    _USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    _USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

    _tmpl, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
        evidence_overrides={
            "prices_used": {_SOL: None, _USDC: 1_000_000, _USDT: 1_000_000},
        },
    )
    await db.commit()

    response = await compute_rebalance_policy_cat(db, run.run_id)
    assert response.result == "fail"
    failing_ids = {c.check_id for c in response.checks if c.result == "fail"}
    assert "price_data_present_check" in failing_ids


@pytest.mark.asyncio
async def test_rebalance_threshold_check_fails_when_deployed_threshold_out_of_range(db):
    """Deployed rebalance_threshold_bps=0 (out of [1,5000]) → check fails on out-of-range clause.

    Source per spec §5.6 line 212 = deployed envelope's `rebalance_threshold_bps`.
    Cat reads from `json.loads(instance.effective_config_json)`, not the artifact's
    `effective_envelope` field (which is evidence/echo, not the policy authority).

    Failure isolation: this test ensures the predicate fails on the OUT-OF-RANGE
    clause specifically, not on the drift/legs consistency clause. With deployed
    `th=0` and a non-empty default legs list (drift_pre=0, has_legs=True):
      - `th_in_range = (1 ≤ 0 ≤ 5000)` = False  ← THE failure cause this test pins
      - `drift_legs_consistent = (0 ≥ 0 and True) or (0 < 0 and not True)` = True
      - Predicate = `False AND True` = False → check fails ONLY because of range.

    Pre-Round-4: this test mutated artifact's effective_envelope, which the Cat
    correctly ignores per Round-2/3 fixes — so it passed incidentally via the
    drift/legs path. Now it tests the actual range clause in isolation.
    """
    from src.integrity.cats.rebalance_policy import compute_rebalance_policy_cat

    bad_envelope = make_rebalance_envelope(rebalance_threshold_bps=0)
    _tmpl, instance, agent = await make_rebalance_instance(
        db, effective_config=bad_envelope,
    )
    # No evidence_overrides: canonical helper emits default planned legs, so
    # has_legs=True. Combined with drift_pre=0 and deployed th=0, the
    # drift/legs consistency clause evaluates to True — isolating the failure
    # to the th_in_range clause.
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
    )
    await db.commit()

    response = await compute_rebalance_policy_cat(db, run.run_id)
    assert response.result == "fail"
    failing_ids = {c.check_id for c in response.checks if c.result == "fail"}
    assert "rebalance_threshold_check" in failing_ids


@pytest.mark.asyncio
async def test_max_trade_value_check_fails_when_leg_exceeds_limit(db):
    """A leg with size_base_units > max_trade_value → max_trade_value_check fails."""
    from src.integrity.cats.rebalance_policy import compute_rebalance_policy_cat

    _SOL = "So11111111111111111111111111111111111111112"
    _tmpl, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
        evidence_overrides={
            "legs": [
                {
                    "mint": _SOL,
                    "side": "BUY",
                    "size_base_units": 2_000_000_000,  # > max_trade_value 1_000_000_000
                    "slippage_bps_realized": 0,
                    "status": "planned",
                },
            ],
        },
    )
    await db.commit()

    response = await compute_rebalance_policy_cat(db, run.run_id)
    assert response.result == "fail"
    failing_ids = {c.check_id for c in response.checks if c.result == "fail"}
    assert "max_trade_value_check" in failing_ids


@pytest.mark.asyncio
async def test_max_position_weight_check_fails_when_deployed_weight_exceeds_limit(db):
    """Deployed target_allocations weight > max_position_weight → check fails.

    Source per spec §5.6 line 214 = deployed envelope (both target_allocations
    and max_position_weight from instance.effective_config_json).
    """
    from src.integrity.cats.rebalance_policy import compute_rebalance_policy_cat

    _SOL = "So11111111111111111111111111111111111111112"
    _USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    _USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
    bad_envelope = make_rebalance_envelope(
        # max_position_weight default is 0.7; SOL=0.8 violates.
        target_allocations={_SOL: 0.8, _USDC: 0.1, _USDT: 0.1},
    )
    _tmpl, instance, agent = await make_rebalance_instance(
        db, effective_config=bad_envelope,
    )
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
    )
    await db.commit()

    response = await compute_rebalance_policy_cat(db, run.run_id)
    assert response.result == "fail"
    failing_ids = {c.check_id for c in response.checks if c.result == "fail"}
    assert "max_position_weight_check" in failing_ids


@pytest.mark.asyncio
async def test_cat_ignores_artifact_target_when_deployed_target_is_valid(db):
    """Codex Round-3 strict-spec lock: artifact's target_allocations is NOT the trust source.

    Per spec §5.6 line 209 ("sum(effective_envelope.target_allocations.values())") and
    spec §5.5 line 192 ("payload.target_allocations is echo of envelope; convenience key"),
    the deployed envelope's target_allocations is authoritative. The artifact's top-level
    target_allocations is for UI/search consumption only — never the Cat's trust source.

    Scenario:
      - Deployed instance: VALID canonical envelope (sum=1.0, all weights ≤ 0.7, all in universe).
      - Artifact's target_allocations: INVALID (sum=0.7 + overweight + outside universe).
      - Expected: target/allocation checks PASS because Cat reads deployed envelope target,
        which is valid. The artifact's invalid target is ignored.
    """
    from src.integrity.cats.rebalance_policy import compute_rebalance_policy_cat

    _SOL = "So11111111111111111111111111111111111111112"
    _USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    # Deployed: valid canonical envelope.
    _tmpl, instance, agent = await make_rebalance_instance(
        db, effective_config=make_rebalance_envelope(),
    )

    # Artifact: invalid target_allocations (sum 0.7, would have failed multiple checks
    # if the Cat trusted the artifact). drift=0 < threshold=50 → no legs for consistency.
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
        evidence_overrides={
            "target_allocations": {_SOL: 0.4, _USDC: 0.3},  # bad sum, missing USDT, etc.
            "legs": [],
        },
    )
    await db.commit()

    response = await compute_rebalance_policy_cat(db, run.run_id)
    failing_ids = {c.check_id for c in response.checks if c.result == "fail"}

    # Cat ignores artifact target → these target/allocation checks all PASS.
    assert "target_allocation_sum_check" not in failing_ids, (
        "Cat read target_allocations from artifact (sum 0.7) instead of deployed envelope (sum 1.0). "
        f"Got failing: {failing_ids}"
    )
    assert "allowed_token_universe_check" not in failing_ids, (
        "Cat read target_allocations from artifact instead of deployed envelope. "
        f"Got failing: {failing_ids}"
    )
    assert "max_position_weight_check" not in failing_ids, (
        "Cat read target_allocations from artifact instead of deployed envelope. "
        f"Got failing: {failing_ids}"
    )


@pytest.mark.asyncio
async def test_cat_catches_deployed_bad_target_even_when_artifact_target_is_valid(db):
    """Inverse strict-spec lock: deployed-bad target → Cat fails despite valid artifact target.

    Scenario:
      - Deployed instance: INVALID envelope (target sum=0.7, bypassing validate_spec_for_template).
      - Artifact's target_allocations: VALID (sum=1.0).
      - Expected: target_allocation_sum_check FAILS because Cat reads deployed envelope.
        The valid artifact target does not "rescue" the bad deployed envelope.
    """
    from src.integrity.cats.rebalance_policy import compute_rebalance_policy_cat

    _SOL = "So11111111111111111111111111111111111111112"
    _USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    _USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

    # Deployed: bad envelope (sum 0.7).
    bad_envelope = make_rebalance_envelope(
        target_allocations={_SOL: 0.4, _USDC: 0.3},  # sum 0.7
    )
    _tmpl, instance, agent = await make_rebalance_instance(
        db, effective_config=bad_envelope,
    )

    # Artifact: valid target (sum=1.0).
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
        evidence_overrides={
            "target_allocations": {_SOL: 0.5, _USDC: 0.3, _USDT: 0.2},  # sum=1.0
        },
    )
    await db.commit()

    response = await compute_rebalance_policy_cat(db, run.run_id)
    failing_ids = {c.check_id for c in response.checks if c.result == "fail"}

    # Cat reads bad deployed (sum=0.7) → check fails despite valid artifact target.
    assert "target_allocation_sum_check" in failing_ids, (
        "Cat must catch deployed envelope's bad sum (0.7) regardless of artifact's valid claim. "
        f"Got failing: {failing_ids}"
    )


@pytest.mark.asyncio
async def test_max_slippage_check_fails_when_leg_has_nonzero_realized_slippage(db):
    """A leg with slippage_bps_realized != 0 → max_slippage_check fails (V0 lock)."""
    from src.integrity.cats.rebalance_policy import compute_rebalance_policy_cat

    _SOL = "So11111111111111111111111111111111111111112"
    _tmpl, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
        evidence_overrides={
            "legs": [
                {
                    "mint": _SOL,
                    "side": "BUY",
                    "size_base_units": 0,
                    "slippage_bps_realized": 5,  # V0 lock requires 0
                    "status": "planned",
                },
            ],
        },
    )
    await db.commit()

    response = await compute_rebalance_policy_cat(db, run.run_id)
    assert response.result == "fail"
    failing_ids = {c.check_id for c in response.checks if c.result == "fail"}
    assert "max_slippage_check" in failing_ids


@pytest.mark.asyncio
async def test_post_trade_allocation_drift_check_fails_when_post_differs_from_pre(db):
    """drift_bps_post_run != drift_bps_pre_run → post_trade_allocation_drift_check fails."""
    from src.integrity.cats.rebalance_policy import compute_rebalance_policy_cat

    _tmpl, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
        evidence_overrides={
            "summary": {
                "drift_bps_pre_run": 0,
                "drift_bps_post_run": 99,  # differs from pre → V0 violation
                "total_traded_value_base_units": 0,
                "max_leg_slippage_bps": 0,
            },
        },
    )
    await db.commit()

    response = await compute_rebalance_policy_cat(db, run.run_id)
    assert response.result == "fail"
    failing_ids = {c.check_id for c in response.checks if c.result == "fail"}
    assert "post_trade_allocation_drift_check" in failing_ids

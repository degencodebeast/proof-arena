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
        db, agent=agent, instance=instance, with_evidence=True
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
    failing = [c for c in resp.checks if c.result == "fail"]
    assert len(failing) == 1
    assert failing[0].check_id == "rebalance_evidence_present_check"
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

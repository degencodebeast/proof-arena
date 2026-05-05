"""Spec §5.6 — RebalancePolicyCatResponse schema mirrors WalletSafetyCatResponse."""
from __future__ import annotations


def test_rebalance_evidence_schema_fields():
    from src.integrity.cats.schemas import RebalancePolicyEvidence
    fields = RebalancePolicyEvidence.model_fields
    # Locked allowlist — never includes uri_or_ref.
    assert "evidence_artifact_id" in fields
    assert "evidence_content_hash" in fields
    assert "run_log_hash" in fields
    assert "primary_event_id" in fields
    assert "verifier_url" in fields
    assert "uri_or_ref" not in fields  # spec §9 private-exposure denylist


def test_rebalance_cat_response_literal_fields():
    from src.integrity.cats.schemas import RebalancePolicyCatResponse
    instance = RebalancePolicyCatResponse(
        run_id=1, instance_id=1,
        subject_type="customized_instance",
        trust_label="benchmark_compatible_customized_instance",
        result="pass",
        run_completion_status="complete",
        evidence={"evidence_artifact_id": None, "evidence_content_hash": None,
                  "run_log_hash": None, "primary_event_id": None, "verifier_url": None},
        checks=[],
    )
    assert instance.cat == "rebalance_policy"
    assert instance.cat_version == "v1"

"""Spec §5.9 — paired demo seed produces a known-good (run_id, artifact) pair."""
import pytest


@pytest.mark.asyncio
async def test_seed_creates_rebalance_run_and_evidence_artifact(db):
    """The seed populates a rebalance run + rebalance_evidence_v1 artifact.

    The seed uses test-helper happy-path prices (per its docstring); this test
    asserts the seed's promise (the (run_id, artifact) tuple is produced and
    consistent), not Cat verdict semantics. Cat verdict is exercised by
    test_rebalance_policy_cat.py and test_verifier_with_rebalance_cat.py.
    """
    from scripts.seed_v2_1_rebalance_smoke_run import run as seed_run
    result = await seed_run(db)
    assert "run_id" in result
    assert "evidence_artifact_id" in result
    assert "evidence_content_hash" in result

    from sqlalchemy import select
    from src.db.models import VerificationArtifact, Run
    run_row = (await db.execute(
        select(Run).where(Run.run_id == result["run_id"])
    )).scalar_one()
    assert run_row.challenge_type == "rebalance_execution"
    assert run_row.completion_status == "complete"

    artifact = (await db.execute(
        select(VerificationArtifact).where(
            VerificationArtifact.run_id == result["run_id"],
            VerificationArtifact.artifact_type == "rebalance_evidence_v1",
        )
    )).scalar_one()
    assert artifact.content_hash == result["evidence_content_hash"]

# agent-rank/backend/tests/integration/test_rebalance_evidence_emit.py
"""Spec §10 test 6 — rebalance evidence emitted once + hash + idempotency."""
from __future__ import annotations

import hashlib
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


def _adapter():
    cfg = make_rebalance_envelope()
    cfg["starting_usdc"] = 100_000_000
    return RebalanceExecutionChallenge(cfg)


@pytest.mark.asyncio
async def test_rebalance_run_emits_one_evidence_artifact(db):
    template, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=False,
    )
    adapter = _adapter()
    await adapter.emit_run_evidence(db, run, events=[])
    rows = (
        await db.execute(
            select(VerificationArtifact).where(
                VerificationArtifact.run_id == run.run_id,
                VerificationArtifact.artifact_type == "rebalance_evidence_v1",
            )
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_rebalance_evidence_payload_validates_canonical_schema(db):
    template, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=False,
    )
    await _adapter().emit_run_evidence(db, run, events=[])
    artifact = (
        await db.execute(
            select(VerificationArtifact).where(
                VerificationArtifact.run_id == run.run_id,
                VerificationArtifact.artifact_type == "rebalance_evidence_v1",
            )
        )
    ).scalar_one()
    payload = json.loads(artifact.uri_or_ref)
    assert payload["evidence_schema_version"] == "rebalance_evidence_v1"
    assert payload["template_key"] == "rebalance_executor_v1"
    assert payload["run_id"] == run.run_id
    assert payload["instance_id"] == instance.instance_id
    assert all(leg["status"] == "planned" for leg in payload["legs"])


@pytest.mark.asyncio
async def test_content_hash_matches_canonical_recipe(db):
    template, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=False,
    )
    await _adapter().emit_run_evidence(db, run, events=[])
    artifact = (
        await db.execute(
            select(VerificationArtifact).where(
                VerificationArtifact.run_id == run.run_id,
                VerificationArtifact.artifact_type == "rebalance_evidence_v1",
            )
        )
    ).scalar_one()
    body = artifact.uri_or_ref
    expected = hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert artifact.content_hash == expected


@pytest.mark.asyncio
async def test_emit_run_evidence_is_idempotent(db):
    template, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=False,
    )
    adapter = _adapter()
    await adapter.emit_run_evidence(db, run, events=[])
    await adapter.emit_run_evidence(db, run, events=[])  # second call: no-op
    rows = (
        await db.execute(
            select(VerificationArtifact).where(
                VerificationArtifact.run_id == run.run_id,
                VerificationArtifact.artifact_type == "rebalance_evidence_v1",
            )
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_swap_run_does_not_emit_rebalance_evidence(db):
    """Negative case: a swap_execution run does NOT produce a rebalance_evidence_v1 row."""
    from tests._rebalance_helpers import make_completed_swap_run, make_swap_instance
    template, instance, agent = await make_swap_instance(db)
    run = await make_completed_swap_run(db, agent=agent, instance=instance)
    rows = (
        await db.execute(
            select(VerificationArtifact).where(
                VerificationArtifact.run_id == run.run_id,
                VerificationArtifact.artifact_type == "rebalance_evidence_v1",
            )
        )
    ).scalars().all()
    assert rows == []

# tests/integration/test_rebalance_evidence_durability.py
"""Defect 1 (HIGH) regression test — commit boundary durability.

Verifies that emit_run_evidence persists the VerificationArtifact such that
a FRESH session (closing the writer session first) can see the row.

Reproduces the production bug where `await db.flush()` leaves the row
visible only inside the same session. In production (FastAPI request path),
get_db() closes the session after the request returns — with only flush, the
artifact is rolled back. The fix is `await db.commit()`.

Design notes:
- Session A = the `db` fixture session (used for setup + calling emit_run_evidence).
- Session B = a fresh session opened from the same test engine AFTER session A closes.
- The test must NOT commit anything itself at the test level; only emit_run_evidence
  is allowed to be the committer of the artifact row.
- We close session A explicitly (via context exit) before querying from session B.
"""
from __future__ import annotations

import json
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
async def test_evidence_artifact_visible_from_fresh_session(engine):
    """Artifact written by emit_run_evidence must be durable across session boundaries.

    This test FAILS before Fix 1 (flush only) because the artifact is not committed
    and is invisible to session B opened after session A closes.
    It PASSES after Fix 1 (commit).
    """
    # Session A: setup + emit
    maker = async_sessionmaker(engine, expire_on_commit=False)
    run_id: int
    async with maker() as db_a:
        template, instance, agent = await make_rebalance_instance(db_a)
        # make_rebalance_instance uses flush internally; commit here so session B
        # can read the setup rows (agent, instance, etc.)
        await db_a.commit()

        run = await make_completed_rebalance_run(
            db_a, agent=agent, instance=instance, with_evidence=False,
        )
        # Commit the run setup so session B can look it up
        await db_a.commit()

        adapter = _adapter()
        await adapter.emit_run_evidence(db_a, run, events=[])
        # Do NOT commit here — only emit_run_evidence should commit the artifact.
        # If emit_run_evidence only flushes, session B will NOT see the row.
        run_id = run.run_id
    # Session A is now closed. If emit_run_evidence only flushed, the artifact is gone.

    # Session B: verify the artifact survived the session boundary
    async with maker() as db_b:
        rows = (
            await db_b.execute(
                select(VerificationArtifact).where(
                    VerificationArtifact.run_id == run_id,
                    VerificationArtifact.artifact_type == "rebalance_evidence_v1",
                )
            )
        ).scalars().all()

    assert len(rows) == 1, (
        "emit_run_evidence must commit the artifact so it survives session closure. "
        f"Got {len(rows)} rows from a fresh session (expected 1). "
        "Fix: replace 'await db.flush()' with 'await db.commit()' in emit_run_evidence."
    )

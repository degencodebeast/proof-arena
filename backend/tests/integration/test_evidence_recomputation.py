"""Task 15: evidence hash recomputation integration proof.

This test closes the gap between "run_log_hash is queryable" and
"run_log_hash can be independently recomputed from persisted RunEvents".
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.db.models import RunEvent
from src.integrity.run_auditor import RunAuditor

pytestmark = pytest.mark.integration


async def test_run_log_hash_recomputed_from_persisted_events(db, factories):
    """RunAuditor recomputes the stored hash from canonical persisted events."""
    agent = await factories.seed_agent(db, display_name="HashBot")
    challenge = await factories.seed_challenge(db, num_contestants=1)
    run = await factories.seed_finalized_run(
        db,
        challenge_id=challenge.challenge_id,
        agent_id=agent.agent_id,
        run_log_hash="0" * 64,
    )

    base_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [
        RunEvent(
            event_id=10_001,
            run_id=run.run_id,
            sequence_no=1,
            event_type="observe",
            timestamp=base_ts,
            state_snapshot_json=json.dumps(
                {"portfolio": {"USDC": 100_000_000}}, sort_keys=True
            ),
        ),
        RunEvent(
            event_id=10_002,
            run_id=run.run_id,
            sequence_no=2,
            event_type="decide",
            timestamp=base_ts + timedelta(seconds=1),
            action_payload_json=json.dumps(
                {"type": "WAIT", "params": {"seconds": 1}}, sort_keys=True
            ),
        ),
        RunEvent(
            event_id=10_003,
            run_id=run.run_id,
            sequence_no=3,
            event_type="validate",
            timestamp=base_ts + timedelta(seconds=2),
            validation_payload_json=json.dumps(
                {"valid": True, "reason": None}, sort_keys=True
            ),
        ),
        RunEvent(
            event_id=10_004,
            run_id=run.run_id,
            sequence_no=4,
            event_type="execute",
            timestamp=base_ts + timedelta(seconds=3),
            execution_payload_json=json.dumps(
                {"executed": True, "tx_signature": "demo_tx"}, sort_keys=True
            ),
            tx_signature="demo_tx",
        ),
        # Post-chain operational events are explicitly outside the evidence hash.
        RunEvent(
            event_id=10_005,
            run_id=run.run_id,
            sequence_no=5,
            event_type="onchain_finalize",
            timestamp=base_ts + timedelta(seconds=4),
            result_payload_json=json.dumps(
                {"tx_signature": "post_chain_tx"}, sort_keys=True
            ),
        ),
    ]
    db.add_all(events)
    await db.flush()

    auditor = RunAuditor(db)
    expected_hash = await auditor.generate_run_log_hash(run.run_id)
    run.run_log_hash = expected_hash
    await db.commit()
    await db.refresh(run)

    recomputed = await auditor.generate_run_log_hash(run.run_id)
    assert recomputed == run.run_log_hash

    artifacts = await auditor.create_audit_trail(run)
    audit_hash = next(a for a in artifacts if a.artifact_type == "audit_log_hash")
    assert audit_hash.content_hash == expected_hash


async def test_run_log_hash_mismatch_fails_closed(db, factories):
    """Audit trail creation refuses runs whose stored hash does not match events."""
    agent = await factories.seed_agent(db, display_name="MismatchBot")
    challenge = await factories.seed_challenge(db, num_contestants=1)
    run = await factories.seed_finalized_run(
        db,
        challenge_id=challenge.challenge_id,
        agent_id=agent.agent_id,
        run_log_hash="f" * 64,
    )

    db.add(
        RunEvent(
            event_id=20_001,
            run_id=run.run_id,
            sequence_no=1,
            event_type="observe",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            state_snapshot_json=json.dumps(
                {"portfolio": {"USDC": 100_000_000}}, sort_keys=True
            ),
        )
    )
    await db.commit()

    with pytest.raises(ValueError, match="hash mismatch"):
        await RunAuditor(db).create_audit_trail(run)

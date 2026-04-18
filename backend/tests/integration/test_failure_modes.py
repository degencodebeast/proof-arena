"""Task 15: Fail-closed behavior for the settlement path.

EDGE-CASE SPEC (fail-closed):

- Invalid runs (completion_status='invalid') CANNOT win settlement.
- Incomplete runs (completion_status='incomplete') CANNOT win settlement.
- Runs missing run_log_hash CANNOT be eligible (evidence required).
- Runs missing ending_value CANNOT be eligible.
- If not all runs are terminal → settlement fails.
- If cardinality mismatch (run count != expected contestants) → settlement fails.
- Settlement is idempotent — second call on an already-completed challenge raises.
- Duplicate agent runs in a challenge → eligibility check raises.
- Settlement without program_client → raises SettlementError (no silent success).

Each test drives SettlementService directly against seeded DB state.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.db.models import Challenge, RankSnapshot, Run
from src.services.settlement_service import SettlementError, SettlementService

pytestmark = pytest.mark.integration


async def test_invalid_run_cannot_win(db, mock_program, factories):
    """An invalid run with high ending_value still loses to a complete run."""
    cheater = await factories.seed_agent(db, display_name="Cheater")
    honest = await factories.seed_agent(db, display_name="Honest")
    challenge = await factories.seed_challenge(db, num_contestants=2)

    # Cheater has higher ending_value but is marked invalid
    await factories.seed_finalized_run(
        db,
        challenge_id=challenge.challenge_id,
        agent_id=cheater.agent_id,
        ending_value=999_999_999,
        completion_status="invalid",
        invalid_reason="invalid_action_attempts_exceeded",
        run_log_hash="c" * 64,
    )
    await factories.seed_finalized_run(
        db,
        challenge_id=challenge.challenge_id,
        agent_id=honest.agent_id,
        ending_value=105_000_000,
        completion_status="complete",
        run_log_hash="h" * 64,
    )

    settlement = SettlementService(db, program_client=mock_program)
    settled = await settlement.settle_challenge(challenge.challenge_id)

    assert settled.winner_agent_id == honest.agent_id, (
        "Cheater with higher ending_value but invalid completion must not win"
    )


async def test_incomplete_run_cannot_win(db, mock_program, factories):
    """An incomplete run is ineligible even with high ending_value."""
    slacker = await factories.seed_agent(db, display_name="Slacker")
    finisher = await factories.seed_agent(db, display_name="Finisher")
    challenge = await factories.seed_challenge(db, num_contestants=2)

    await factories.seed_finalized_run(
        db,
        challenge_id=challenge.challenge_id,
        agent_id=slacker.agent_id,
        ending_value=500_000_000,
        completion_status="incomplete",
        run_log_hash="s" * 64,
    )
    await factories.seed_finalized_run(
        db,
        challenge_id=challenge.challenge_id,
        agent_id=finisher.agent_id,
        ending_value=102_000_000,
        completion_status="complete",
        run_log_hash="f" * 64,
    )

    settlement = SettlementService(db, program_client=mock_program)
    settled = await settlement.settle_challenge(challenge.challenge_id)

    assert settled.winner_agent_id == finisher.agent_id


async def test_missing_evidence_hash_ineligible(db, mock_program, factories):
    """A run without run_log_hash cannot be a winner."""
    no_evidence = await factories.seed_agent(db, display_name="NoEvidence")
    good = await factories.seed_agent(db, display_name="Good")
    challenge = await factories.seed_challenge(db, num_contestants=2)

    await factories.seed_finalized_run(
        db,
        challenge_id=challenge.challenge_id,
        agent_id=no_evidence.agent_id,
        ending_value=900_000_000,
        completion_status="complete",
        run_log_hash=None,  # MISSING
    )
    await factories.seed_finalized_run(
        db,
        challenge_id=challenge.challenge_id,
        agent_id=good.agent_id,
        ending_value=101_000_000,
        completion_status="complete",
        run_log_hash="g" * 64,
    )

    settlement = SettlementService(db, program_client=mock_program)
    settled = await settlement.settle_challenge(challenge.challenge_id)

    assert settled.winner_agent_id == good.agent_id, (
        "Run without run_log_hash must be ineligible"
    )


async def test_not_all_terminal_cannot_settle(db, mock_program, factories):
    """If any run is non-terminal, settlement fails."""
    agent_a = await factories.seed_agent(db, display_name="A")
    agent_b = await factories.seed_agent(db, display_name="B")
    challenge = await factories.seed_challenge(db, num_contestants=2)

    await factories.seed_finalized_run(
        db,
        challenge_id=challenge.challenge_id,
        agent_id=agent_a.agent_id,
        status="running",  # NOT terminal
        completion_status=None,
        ending_value=None,
        run_log_hash=None,
    )
    await factories.seed_finalized_run(
        db,
        challenge_id=challenge.challenge_id,
        agent_id=agent_b.agent_id,
        completion_status="complete",
        run_log_hash="b" * 64,
    )

    settlement = SettlementService(db, program_client=mock_program)
    with pytest.raises(SettlementError) as exc:
        await settlement.settle_challenge(challenge.challenge_id)
    assert "terminal" in str(exc.value).lower()


async def test_settlement_idempotent(db, mock_program, factories):
    """Settling an already-completed challenge raises SettlementError."""
    a = await factories.seed_agent(db, display_name="A")
    b = await factories.seed_agent(db, display_name="B")
    challenge = await factories.seed_challenge(db, num_contestants=2)
    await factories.seed_finalized_run(
        db, challenge_id=challenge.challenge_id, agent_id=a.agent_id,
        ending_value=100_000_000, run_log_hash="a" * 64,
    )
    await factories.seed_finalized_run(
        db, challenge_id=challenge.challenge_id, agent_id=b.agent_id,
        ending_value=105_000_000, run_log_hash="b" * 64,
    )

    settlement = SettlementService(db, program_client=mock_program)
    await settlement.settle_challenge(challenge.challenge_id)

    # Second call must fail
    with pytest.raises(SettlementError) as exc:
        await settlement.settle_challenge(challenge.challenge_id)
    assert "already settled" in str(exc.value).lower()


async def test_settlement_without_program_client_fails_closed(db, factories):
    """No program_client means no on-chain anchor, so settlement must refuse."""
    a = await factories.seed_agent(db, display_name="A")
    challenge = await factories.seed_challenge(db, num_contestants=1)
    await factories.seed_finalized_run(
        db, challenge_id=challenge.challenge_id, agent_id=a.agent_id,
        ending_value=100_000_000, run_log_hash="a" * 64,
    )

    settlement = SettlementService(db, program_client=None)
    with pytest.raises(SettlementError) as exc:
        await settlement.settle_challenge(challenge.challenge_id)
    assert "program client" in str(exc.value).lower() or "on-chain" in str(exc.value).lower()


async def test_cardinality_mismatch_cannot_settle(db, mock_program, factories):
    """Fewer runs than num_contestants → settlement fails."""
    a = await factories.seed_agent(db, display_name="A")
    challenge = await factories.seed_challenge(db, num_contestants=3)  # expects 3
    # Only one run
    await factories.seed_finalized_run(
        db, challenge_id=challenge.challenge_id, agent_id=a.agent_id,
        ending_value=100_000_000, run_log_hash="a" * 64,
    )

    settlement = SettlementService(db, program_client=mock_program)
    with pytest.raises(SettlementError) as exc:
        await settlement.settle_challenge(challenge.challenge_id)
    assert "cardinality" in str(exc.value).lower() or "settle" in str(exc.value).lower()

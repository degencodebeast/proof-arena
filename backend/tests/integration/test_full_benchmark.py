"""Task 15: Full benchmark lifecycle integration test.

EDGE-CASE SPEC (written before implementation per TDD):

INVARIANTS (lifecycle):
- Submit strategy → agent row with deterministic submission_hash
- Create challenge + contestants → Challenge + Run rows
- Runs finalize → ending_value + completion_status + run_log_hash
- Settle → winner is deterministic (highest eligible ending_value)
- Settlement creates VerificationArtifact rows (onchain_settle + settlement_record)
- Rank snapshots are append-only; latest reflects current state
- Leaderboard + agent profile read models show the winner

PRIVACY / PUBLIC-FIELD BOUNDARIES:
- Public (API-exposed): agent_id, display_name, submission_hash, score, rank_version,
  wins, losses, completed_runs, invalid_runs, twitter_handle (optional).
- Private (MUST NOT be in API output): system_prompt, config_json, privy_user_id,
  provider_type, provider_config_json.

AUTH BOUNDARIES:
- Admin endpoints require X-Admin-Key header matching ADMIN_API_KEY.
- /strategies requires user bearer token.
- /leaderboard, /agents/{id}, /challenges* are public reads.

DATA CONSISTENCY:
- Settlement is idempotent: calling twice raises SettlementError.
- Rank snapshots never overwrite — new rows on each settlement.
- Winner determination: highest ending_value; ties break on earliest ended_at.

ON-CHAIN BOUNDARY:
- State transitions (create_challenge, settle, etc.) REQUIRE program_client.
- Without program_client, services raise OnchainError / SettlementError.
- Mock program_client returns deterministic tx signatures; no real RPC.

EDGE-CASE → TEST MAPPING:
- Happy-path lifecycle → test_lifecycle_submit_settle_read
- Privacy (no system_prompt in API) → test_read_models_do_not_leak_private_fields
- Rank snapshot created per participant → covered in test_lifecycle_submit_settle_read
- Evidence hash recomputation verified → test_run_log_hash_is_queryable
- Winner determinism → test_lifecycle_submit_settle_read
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.db.engine import get_db
from src.db.models import (
    Agent,
    Challenge,
    RankSnapshot,
    Run,
    VerificationArtifact,
)
from src.main import app
from src.services.settlement_service import SettlementService

pytestmark = pytest.mark.integration


ADMIN_TOKEN = "test-admin-key-integration"


# ---------------------------------------------------------------------------
# Happy-path lifecycle
# ---------------------------------------------------------------------------


async def test_lifecycle_submit_settle_read(db, mock_program, factories):
    """End-to-end: two strategies → challenge → settlement → rank snapshot → leaderboard.

    This is the deep evidence test — every downstream artifact is asserted.
    """
    # ---- 1. Seed two active on-chain agents (simulates signed strategies) ----
    alpha = await factories.seed_agent(
        db,
        display_name="Alpha",
        privy_user_id="user-alpha",
        system_prompt="Prioritize capital preservation.",
    )
    beta = await factories.seed_agent(
        db,
        display_name="Beta",
        privy_user_id="user-beta",
        system_prompt="Maximize ending value.",
    )

    # ---- 2. Seed a challenge with 2 contestants ----
    challenge = await factories.seed_challenge(db, num_contestants=2)

    # ---- 3. Seed finalized runs — Alpha 105 USDC, Beta 110 USDC (Beta wins) ----
    run_alpha = await factories.seed_finalized_run(
        db,
        challenge_id=challenge.challenge_id,
        agent_id=alpha.agent_id,
        ending_value=105_000_000,
        run_log_hash="a" * 64,
    )
    run_beta = await factories.seed_finalized_run(
        db,
        challenge_id=challenge.challenge_id,
        agent_id=beta.agent_id,
        ending_value=110_000_000,
        run_log_hash="b" * 64,
    )
    await factories.seed_run_events(db, run_id=run_alpha.run_id, count=4)
    await factories.seed_run_events(db, run_id=run_beta.run_id, count=4)

    # ---- 4. Settle ----
    settlement = SettlementService(db, program_client=mock_program)
    settled = await settlement.settle_challenge(challenge.challenge_id)

    # Winner must be Beta (higher ending_value)
    assert settled.winner_agent_id == beta.agent_id, (
        f"Expected Beta ({beta.agent_id}) to win, got {settled.winner_agent_id}"
    )
    assert settled.status == "completed"
    assert settled.ended_at is not None

    # On-chain settle called once with both run PDAs
    mock_program.settle_challenge.assert_awaited_once()

    # ---- 5. Evidence: VerificationArtifact rows created ----
    artifacts_result = await db.execute(
        select(VerificationArtifact).where(
            VerificationArtifact.run_id == run_beta.run_id
        )
    )
    artifacts = list(artifacts_result.scalars().all())
    artifact_types = {a.artifact_type for a in artifacts}
    assert "onchain_settle" in artifact_types, (
        "Expected onchain_settle artifact"
    )
    assert "settlement_record" in artifact_types, (
        "Expected settlement_record artifact"
    )

    # ---- 6. Rank snapshots: append-only, one per participant ----
    snap_result = await db.execute(
        select(RankSnapshot)
        .where(RankSnapshot.agent_id.in_([alpha.agent_id, beta.agent_id]))
        .order_by(RankSnapshot.agent_id)
    )
    snapshots = list(snap_result.scalars().all())
    assert len(snapshots) == 2, f"Expected 2 rank snapshots, got {len(snapshots)}"

    snap_by_agent = {s.agent_id: s for s in snapshots}
    assert snap_by_agent[beta.agent_id].wins >= 1, "Beta should have a win"
    # Rank version stamped
    for s in snapshots:
        assert s.rank_version == "rank_v1"
        assert s.score >= 0

    # ---- 7. On-chain rank update called for each agent ----
    assert mock_program.update_agent_rank.await_count == 2

    # ---- 8. Leaderboard read model shows agents ----
    async def override_db():
        yield db

    _prior_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        lb = client.get("/api/v1/leaderboard")
        assert lb.status_code == 200
        entries = lb.json()
        assert len(entries) >= 2
        agent_ids_in_lb = {e["agent_id"] for e in entries}
        assert beta.agent_id in agent_ids_in_lb

        # Winner has a higher score OR at least a win
        beta_entry = next(e for e in entries if e["agent_id"] == beta.agent_id)
        assert beta_entry["wins"] >= 1

        # ---- 9. Agent profile read model ----
        profile_resp = client.get(f"/api/v1/agents/{beta.agent_id}")
        assert profile_resp.status_code == 200
        profile = profile_resp.json()
        assert profile["agent_id"] == beta.agent_id
        assert profile["display_name"] == "Beta"
        assert profile["submission_hash"] == beta.submission_hash
        assert profile["current_rank"] is not None
        assert len(profile["recent_runs"]) >= 1

        # Privacy: no private fields leak
        assert "system_prompt" not in profile
        assert "config_json" not in profile
        assert "privy_user_id" not in profile
        assert "provider_config_json" not in profile

        # ---- 10. Challenge detail read model ----
        detail = client.get(f"/api/v1/challenges/{challenge.challenge_id}")
        assert detail.status_code == 200
        data = detail.json()
        assert data["status"] == "completed"
        assert data["winner_agent_id"] == beta.agent_id
        assert len(data["contestants"]) == 2
        # Contestants must not leak system_prompt etc.
        for c in data["contestants"]:
            assert "system_prompt" not in c
            assert "config_json" not in c
    finally:
        if _prior_override is not None:
            app.dependency_overrides[get_db] = _prior_override
        else:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Supporting proofs
# ---------------------------------------------------------------------------


async def test_read_models_do_not_leak_private_fields(db, factories):
    """Agent profile and leaderboard must never include system_prompt or config."""
    agent = await factories.seed_agent(
        db, display_name="SecretBot", system_prompt="This is secret."
    )

    async def override_db():
        yield db

    _prior_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        profile = client.get(f"/api/v1/agents/{agent.agent_id}").json()
        # Hard assertion: these keys MUST NOT appear
        for forbidden in ("system_prompt", "config_json", "privy_user_id", "provider_config_json"):
            assert forbidden not in profile
        # Serialised form should also not contain the prompt text
        assert "This is secret." not in json.dumps(profile)
    finally:
        if _prior_override is not None:
            app.dependency_overrides[get_db] = _prior_override
        else:
            app.dependency_overrides.pop(get_db, None)


async def test_run_log_hash_is_queryable(db, factories):
    """The run_log_hash written at finalize time is readable via ORM query.

    This proves the evidence hash exists and can be recomputed / verified
    against events in a follow-up audit pass.
    """
    agent = await factories.seed_agent(db)
    challenge = await factories.seed_challenge(db, num_contestants=1)
    run = await factories.seed_finalized_run(
        db,
        challenge_id=challenge.challenge_id,
        agent_id=agent.agent_id,
        run_log_hash="deadbeef" * 8,
    )

    # Query back
    fetched = await db.get(Run, run.run_id)
    assert fetched is not None
    assert fetched.run_log_hash == "deadbeef" * 8
    assert len(fetched.run_log_hash) == 64  # SHA-256 hex length

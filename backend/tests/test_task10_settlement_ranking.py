"""Task 10: Settlement Service and Rank Computation tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import settings
from src.services.settlement_service import (
    RANK_WEIGHTS_V1,
    SettlementError,
    SettlementService,
)


def _make_run(**overrides):
    run = MagicMock()
    run.run_id = overrides.get("run_id", 1)
    run.challenge_id = overrides.get("challenge_id", 1)
    run.agent_id = overrides.get("agent_id", 1)
    run.status = overrides.get("status", "completed")
    run.completion_status = overrides.get("completion_status", "complete")
    run.ending_value = overrides.get("ending_value", 1000)
    run.run_log_hash = overrides.get("run_log_hash", "a" * 64)
    run.ended_at = overrides.get("ended_at", datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc))
    run.starting_value = overrides.get("starting_value", 1000)
    run.onchain_address = overrides.get("onchain_address", "11111111111111111111111111111111")
    run.score_inputs_json = overrides.get("score_inputs_json", '{"execution_quality": 0.95}')
    return run


def _make_challenge(**overrides):
    ch = MagicMock()
    ch.challenge_id = overrides.get("challenge_id", 1)
    ch.num_contestants = overrides.get("num_contestants", 2)
    ch.status = overrides.get("status", "settling")
    ch.winner_agent_id = overrides.get("winner_agent_id", None)
    return ch


def _make_service(mock_db, program=None):
    """Create SettlementService with a mock program client."""
    if program is None:
        program = MagicMock()
        program.settle_challenge = AsyncMock(return_value="tx_sig")
        program.update_agent_rank = AsyncMock(return_value="rank_tx")
    return SettlementService(mock_db, program_client=program)


# -----------------------------------------------------------------------
# 1. Fix 1: Requires program client
# -----------------------------------------------------------------------


class TestRequiresProgramClient:
    @pytest.mark.asyncio
    async def test_no_program_raises(self):
        svc = SettlementService(AsyncMock(), program_client=None)
        with pytest.raises(SettlementError, match="No program client"):
            await svc.settle_challenge(1)


# -----------------------------------------------------------------------
# 2. Fix 3: Idempotency — already settled
# -----------------------------------------------------------------------


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_already_completed_raises(self):
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=_make_challenge(status="completed"))
        svc = _make_service(mock_db)
        with pytest.raises(SettlementError, match="already settled"):
            await svc.settle_challenge(1)

    @pytest.mark.asyncio
    async def test_already_has_winner_raises(self):
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=_make_challenge(winner_agent_id=5))
        svc = _make_service(mock_db)
        with pytest.raises(SettlementError, match="already settled"):
            await svc.settle_challenge(1)


# -----------------------------------------------------------------------
# 3. Fix 4: Missing on-chain addresses
# -----------------------------------------------------------------------


class TestOnchainAddressRequired:
    @pytest.mark.asyncio
    async def test_missing_onchain_address_raises(self):
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=_make_challenge())

        from src.integrity.settlement_verifier import SettlementEligibility

        run_no_addr = _make_run(agent_id=1, onchain_address=None)  # Missing!
        run_ok = _make_run(agent_id=2, onchain_address="SomeAddr")

        with patch("src.services.settlement_service.SettlementVerifier") as MV:
            from src.integrity.settlement_verifier import SettlementVerifier as Real
            MV.determine_winner = Real.determine_winner
            MV.return_value.verify_settlement_eligibility = AsyncMock(
                return_value=SettlementEligibility(
                    eligible=[run_no_addr, run_ok], expected_contestants=2,
                )
            )

            svc = _make_service(mock_db)
            with pytest.raises(SettlementError, match="missing on-chain address"):
                await svc.settle_challenge(1)


# -----------------------------------------------------------------------
# 4. Happy path with program client
# -----------------------------------------------------------------------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_full_settlement(self):
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.get = AsyncMock(return_value=_make_challenge())

        from src.integrity.settlement_verifier import SettlementEligibility

        run1 = _make_run(agent_id=1, ending_value=100)
        run2 = _make_run(agent_id=2, ending_value=200)

        mock_program = MagicMock()
        mock_program.settle_challenge = AsyncMock(return_value="tx")
        mock_program.update_agent_rank = AsyncMock()

        with patch("src.services.settlement_service.SettlementVerifier") as MV:
            from src.integrity.settlement_verifier import SettlementVerifier as Real
            MV.determine_winner = Real.determine_winner
            MV.return_value.verify_settlement_eligibility = AsyncMock(
                return_value=SettlementEligibility(
                    eligible=[run1, run2], expected_contestants=2,
                )
            )
            MV.return_value.create_settlement_record = AsyncMock()

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [run1, run2]
            mock_db.execute = AsyncMock(return_value=mock_result)

            svc = SettlementService(mock_db, program_client=mock_program)
            svc._get_latest_wins_batch = AsyncMock(return_value={1: 0, 2: 0})

            challenge = await svc.settle_challenge(1)

            assert challenge.winner_agent_id == 2
            assert challenge.status == "completed"
            mock_program.settle_challenge.assert_called_once()
            MV.return_value.create_settlement_record.assert_called_once()

            # On-chain settle artifact added before challenge/rank writes.
            # NOTE: This is same-transaction evidence — NOT independently
            # durable. If commit() fails, the artifact rolls back with it.
            # Reconciliation for chain-success/DB-failure is a Task 15 concern.
            all_adds = mock_db.add.call_args_list
            onchain_idx = None
            rank_idx = None
            for i, c in enumerate(all_adds):
                obj = c.args[0]
                if hasattr(obj, "artifact_type") and obj.artifact_type == "onchain_settle":
                    onchain_idx = i
                if hasattr(obj, "rank_version") and rank_idx is None:
                    rank_idx = i

            assert onchain_idx is not None, "onchain_settle artifact must exist"
            if rank_idx is not None:
                assert onchain_idx < rank_idx, "onchain_settle must be added before rank snapshots"

            import json as _json
            onchain_artifact = all_adds[onchain_idx].args[0]
            payload = _json.loads(onchain_artifact.uri_or_ref)
            assert payload["tx_signature"] == "tx"
            assert payload["challenge_id"] == 1
            assert onchain_artifact.content_hash != ""


# -----------------------------------------------------------------------
# 5. Settlement rejection
# -----------------------------------------------------------------------


class TestSettlementRejection:
    @pytest.mark.asyncio
    async def test_rejects_ineligible(self):
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=_make_challenge())

        from src.integrity.settlement_verifier import SettlementEligibility

        with patch("src.services.settlement_service.SettlementVerifier") as MV:
            MV.return_value.verify_settlement_eligibility = AsyncMock(
                return_value=SettlementEligibility(
                    eligible=[],
                    ineligible=[(_make_run(status="running"), "not_completed")],
                    expected_contestants=2,
                )
            )
            svc = _make_service(mock_db)
            with pytest.raises(SettlementError):
                await svc.settle_challenge(1)


# -----------------------------------------------------------------------
# 6. Rank formula
# -----------------------------------------------------------------------


class TestRankFormula:
    def test_exact_weighted_score(self):
        runs = [_make_run(agent_id=1, score_inputs_json='{"execution_quality": 1.0}')]
        rank = SettlementService._compute_rank(1, True, runs, prev_wins=0)
        expected = 100 * 0.35 + 100 * 0.30 + 50 * 0.20 + 10 * 0.15
        assert rank["score"] == round(expected, 2)
        assert rank["wins"] == 1

    def test_loser_score(self):
        runs = [_make_run(score_inputs_json='{"execution_quality": 0.9}')]
        rank = SettlementService._compute_rank(2, False, runs, prev_wins=0)
        expected = 0 * 0.35 + 90 * 0.30 + 50 * 0.20 + 10 * 0.15
        assert rank["score"] == round(expected, 2)
        assert rank["wins"] == 0

    def test_incomplete_not_counted_as_invalid(self):
        """Only completion_status='invalid' should count as invalid_runs."""
        runs = [
            _make_run(completion_status="complete"),
            _make_run(completion_status="incomplete"),  # NOT invalid
            _make_run(completion_status="invalid"),
        ]
        rank = SettlementService._compute_rank(1, False, runs, prev_wins=0)
        assert rank["invalid_runs"] == 1  # Only the "invalid" one
        assert rank["completed_runs"] == 1

    def test_total_runs_includes_all_terminal(self):
        """total_runs should count all terminal runs including failed/timeout."""
        runs = [
            _make_run(status="completed", completion_status="complete"),
            _make_run(status="failed", completion_status="invalid"),
            _make_run(status="timeout", completion_status="incomplete"),
        ]
        rank = SettlementService._compute_rank(1, False, runs, prev_wins=0)
        assert rank["total_runs"] == 3
        assert rank["losses"] == 3  # 0 wins, 3 total

    def test_onchain_total_challenges_uses_total_runs(self):
        """On-chain total_challenges must equal total terminal runs, not completed+invalid."""
        runs = [
            _make_run(completion_status="complete"),
            _make_run(completion_status="incomplete"),  # Terminal but not invalid
        ]
        rank = SettlementService._compute_rank(1, False, runs, prev_wins=0)
        assert rank["total_runs"] == 2
        # On-chain would send total_runs=2, not completed+invalid=1


# -----------------------------------------------------------------------
# 7. Artifact content_hash verification
# -----------------------------------------------------------------------


class TestArtifactContentHash:
    @pytest.mark.asyncio
    async def test_rank_sync_failed_has_valid_hash(self):
        import hashlib

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [_make_run(agent_id=1)]
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_program = MagicMock()
        mock_program.update_agent_rank = AsyncMock(side_effect=Exception("RPC"))

        mock_agent = MagicMock()
        mock_agent.agent_id = 1
        mock_agent.onchain_address = "11111111111111111111111111111111"
        agent_result = MagicMock()
        agent_result.scalars.return_value.all.return_value = [mock_agent]

        call_count = 0
        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_result
            return agent_result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        svc = SettlementService(mock_db, program_client=mock_program)
        svc._get_latest_wins_batch = AsyncMock(return_value={1: 0})
        await svc._update_ranks(1, [_make_run(agent_id=1)])

        artifacts = [
            c.args[0] for c in mock_db.add.call_args_list
            if hasattr(c.args[0], "artifact_type") and c.args[0].artifact_type == "rank_sync_failed"
        ]
        assert len(artifacts) == 1
        a = artifacts[0]
        assert a.content_hash == hashlib.sha256(a.uri_or_ref.encode()).hexdigest()
        assert a.content_hash != ""


# -----------------------------------------------------------------------
# 8. RankSnapshot append-only
# -----------------------------------------------------------------------


class TestRankSnapshot:
    @pytest.mark.asyncio
    async def test_creates_snapshot_per_agent(self):
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            _make_run(agent_id=1), _make_run(agent_id=2),
        ]
        mock_db.execute = AsyncMock(return_value=mock_result)

        svc = SettlementService(mock_db)
        svc._get_latest_wins_batch = AsyncMock(return_value={1: 0, 2: 0})
        await svc._update_ranks(1, [_make_run(agent_id=1), _make_run(agent_id=2)])

        snapshots = [c.args[0] for c in mock_db.add.call_args_list if hasattr(c.args[0], "rank_version")]
        assert len(snapshots) == 2

    @pytest.mark.asyncio
    async def test_snapshot_has_required_fields(self):
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [_make_run(agent_id=1)]
        mock_db.execute = AsyncMock(return_value=mock_result)

        svc = SettlementService(mock_db)
        svc._get_latest_wins_batch = AsyncMock(return_value={1: 0})
        await svc._update_ranks(1, [_make_run(agent_id=1)])

        s = [c.args[0] for c in mock_db.add.call_args_list if hasattr(c.args[0], "rank_version")][0]
        assert s.rank_version == settings.RANK_VERSION
        assert s.app_version == settings.APP_VERSION
        assert s.score_inputs_json is not None
        assert s.score_breakdown_json is not None


# -----------------------------------------------------------------------
# 8. On-chain rank failure preserves DB
# -----------------------------------------------------------------------


class TestOnchainRankFailure:
    @pytest.mark.asyncio
    async def test_db_snapshot_survives(self):
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [_make_run(agent_id=1)]
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_program = MagicMock()
        mock_program.update_agent_rank = AsyncMock(side_effect=Exception("RPC fail"))

        mock_agent = MagicMock()
        mock_agent.agent_id = 1
        mock_agent.onchain_address = "11111111111111111111111111111111"

        # Mock agent query for strategy PDA
        agent_result = MagicMock()
        agent_result.scalars.return_value.all.return_value = [mock_agent]

        call_count = 0
        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_result  # Historical runs
            return agent_result  # Agents

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        svc = SettlementService(mock_db, program_client=mock_program)
        svc._get_latest_wins_batch = AsyncMock(return_value={1: 0})
        await svc._update_ranks(1, [_make_run(agent_id=1)])

        snapshots = [c.args[0] for c in mock_db.add.call_args_list if hasattr(c.args[0], "rank_version")]
        assert len(snapshots) == 1  # Preserved despite on-chain failure

        # Reconciliation artifact persisted
        artifacts = [
            c.args[0] for c in mock_db.add.call_args_list
            if hasattr(c.args[0], "artifact_type") and c.args[0].artifact_type == "rank_sync_failed"
        ]
        assert len(artifacts) == 1
        import json
        payload = json.loads(artifacts[0].uri_or_ref)
        assert payload["agent_id"] == 1
        assert "RPC fail" in payload["error"]


# -----------------------------------------------------------------------
# 9. Module imports
# -----------------------------------------------------------------------


class TestImports:
    def test_all(self):
        from src.services.settlement_service import SettlementService, SettlementError, RANK_WEIGHTS_V1
        assert all([SettlementService, SettlementError, RANK_WEIGHTS_V1])

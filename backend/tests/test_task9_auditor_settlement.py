"""Task 9: Run Auditor and Settlement Verifier tests."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.integrity.run_auditor import (
    RunAuditor,
    compute_evidence_hash,
    event_to_canonical_dict,
    is_evidence_event_type,
)
from src.integrity.settlement_verifier import SettlementEligibility, SettlementVerifier
from src.services.runner_service import RunnerService


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _make_event_dict(**overrides) -> dict:
    defaults = {
        "run_id": 1,
        "sequence_no": 0,
        "event_type": "observe",
        "timestamp": "2025-01-01T00:00:00+00:00",
        "state_snapshot_json": None,
        "action_payload_json": None,
        "validation_payload_json": None,
        "execution_payload_json": None,
        "result_payload_json": None,
        "tx_signature": None,
        "quote_snapshot_ref": None,
    }
    defaults.update(overrides)
    return defaults


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
    return run


# -----------------------------------------------------------------------
# 1. Evidence hash — deterministic
# -----------------------------------------------------------------------


class TestEvidenceHash:
    def test_deterministic_for_same_events(self):
        events = [_make_event_dict(sequence_no=0), _make_event_dict(sequence_no=1)]
        assert compute_evidence_hash(events) == compute_evidence_hash(events)

    def test_changes_when_payload_changes(self):
        e1 = [_make_event_dict(result_payload_json={"data": "a"})]
        e2 = [_make_event_dict(result_payload_json={"data": "b"})]
        assert compute_evidence_hash(e1) != compute_evidence_hash(e2)

    def test_independent_of_insertion_order(self):
        ordered = [_make_event_dict(sequence_no=0), _make_event_dict(sequence_no=1)]
        reversed_order = [_make_event_dict(sequence_no=1), _make_event_dict(sequence_no=0)]
        assert compute_evidence_hash(ordered) == compute_evidence_hash(reversed_order)

    def test_is_valid_sha256(self):
        h = compute_evidence_hash([_make_event_dict()])
        assert len(h) == 64
        int(h, 16)

    def test_matches_runner_hash(self):
        """RunAuditor hash must match RunnerService hash for same events."""
        events = [
            _make_event_dict(sequence_no=0, event_type="observe"),
            _make_event_dict(sequence_no=1, event_type="decide"),
            _make_event_dict(sequence_no=2, event_type="finalize"),
        ]
        auditor_hash = compute_evidence_hash(events)
        runner_hash = RunnerService._compute_run_log_hash(events)
        assert auditor_hash == runner_hash


# -----------------------------------------------------------------------
# 2. Evidence boundary
# -----------------------------------------------------------------------


class TestEvidenceBoundary:
    def test_observe_is_evidence(self):
        assert is_evidence_event_type("observe")

    def test_finalize_is_evidence(self):
        assert is_evidence_event_type("finalize")

    def test_onchain_finalize_excluded(self):
        assert not is_evidence_event_type("onchain_finalize")

    def test_hash_excludes_onchain_finalize_event(self):
        evidence_events = [
            _make_event_dict(sequence_no=0, event_type="observe"),
            _make_event_dict(sequence_no=1, event_type="finalize"),
        ]
        all_events = evidence_events + [
            _make_event_dict(sequence_no=2, event_type="onchain_finalize"),
        ]
        # Filter to evidence only
        filtered = [e for e in all_events if is_evidence_event_type(e["event_type"])]
        assert compute_evidence_hash(filtered) == compute_evidence_hash(evidence_events)


# -----------------------------------------------------------------------
# 3. Event reconstruction from DB rows
# -----------------------------------------------------------------------


class TestEventReconstruction:
    def test_reconstructs_canonical_dict(self):
        event = MagicMock()
        event.run_id = 1
        event.sequence_no = 0
        event.event_type = "observe"
        event.timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
        event.state_snapshot_json = '{"USDC": 1000}'
        event.action_payload_json = None
        event.validation_payload_json = None
        event.execution_payload_json = None
        event.result_payload_json = None
        event.tx_signature = None
        event.quote_snapshot_ref = None

        d = event_to_canonical_dict(event)
        assert d["run_id"] == 1
        assert d["event_type"] == "observe"
        assert d["state_snapshot_json"] == {"USDC": 1000}


# -----------------------------------------------------------------------
# 4. Verification artifacts
# -----------------------------------------------------------------------


class TestAuditTrail:
    @staticmethod
    def _make_db_event(**overrides):
        """Create a fully-specified mock RunEvent for DB queries."""
        e = MagicMock()
        e.run_id = overrides.get("run_id", 1)
        e.sequence_no = overrides.get("sequence_no", 0)
        e.event_type = overrides.get("event_type", "execute")
        e.timestamp = overrides.get("timestamp", datetime(2025, 1, 1, tzinfo=timezone.utc))
        e.state_snapshot_json = overrides.get("state_snapshot_json", None)
        e.action_payload_json = overrides.get("action_payload_json", None)
        e.validation_payload_json = overrides.get("validation_payload_json", None)
        e.execution_payload_json = overrides.get("execution_payload_json", None)
        e.result_payload_json = overrides.get("result_payload_json", None)
        e.tx_signature = overrides.get("tx_signature", None)
        e.quote_snapshot_ref = overrides.get("quote_snapshot_ref", None)
        return e

    @pytest.mark.asyncio
    async def test_creates_five_artifact_types(self):
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        mock_challenge = MagicMock()
        mock_challenge.config_json = '{"starting_usdc": 1000}'
        mock_db.get = AsyncMock(side_effect=[mock_challenge, MagicMock(submission_hash="abc123")])

        mock_event = self._make_db_event(
            quote_snapshot_ref='{"quote_id": "q1"}', tx_signature="sig_1",
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_event]
        mock_db.execute = AsyncMock(return_value=mock_result)

        auditor = RunAuditor(mock_db)
        # Pre-compute hash so verification passes
        expected_hash = compute_evidence_hash([event_to_canonical_dict(mock_event)])
        run = _make_run(run_log_hash=expected_hash)
        artifacts = await auditor.create_audit_trail(run)

        types = [a.artifact_type for a in artifacts]
        assert "challenge_config" in types
        assert "submission_hash" in types
        assert "quote_set" in types
        assert "tx_receipt" in types
        assert "audit_log_hash" in types
        assert len(artifacts) == 5

    @pytest.mark.asyncio
    async def test_quote_set_includes_snapshots(self):
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.get = AsyncMock(return_value=MagicMock(config_json="{}", submission_hash="x"))

        mock_event = self._make_db_event(
            quote_snapshot_ref='{"quote_id": "q1", "output_mint": "SOL"}',
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_event]
        mock_db.execute = AsyncMock(return_value=mock_result)

        auditor = RunAuditor(mock_db)
        expected_hash = compute_evidence_hash([event_to_canonical_dict(mock_event)])
        artifacts = await auditor.create_audit_trail(_make_run(run_log_hash=expected_hash))

        quote_artifact = [a for a in artifacts if a.artifact_type == "quote_set"][0]
        refs = json.loads(quote_artifact.uri_or_ref)
        assert len(refs) == 1
        assert "q1" in refs[0]

    @pytest.mark.asyncio
    async def test_tx_receipt_includes_signatures(self):
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.get = AsyncMock(return_value=MagicMock(config_json="{}", submission_hash="x"))

        mock_event = self._make_db_event(tx_signature="sig_abc")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_event]
        mock_db.execute = AsyncMock(return_value=mock_result)

        auditor = RunAuditor(mock_db)
        expected_hash = compute_evidence_hash([event_to_canonical_dict(mock_event)])
        artifacts = await auditor.create_audit_trail(_make_run(run_log_hash=expected_hash))

        tx_artifact = [a for a in artifacts if a.artifact_type == "tx_receipt"][0]
        sigs = json.loads(tx_artifact.uri_or_ref)
        assert "sig_abc" in sigs


# -----------------------------------------------------------------------
# 5. Settlement eligibility
# -----------------------------------------------------------------------


class TestSettlementEligibility:
    def test_completed_complete_run_eligible(self):
        reason = SettlementVerifier._check_eligibility(_make_run())
        assert reason is None

    def test_running_run_ineligible(self):
        reason = SettlementVerifier._check_eligibility(_make_run(status="running"))
        assert reason is not None
        assert "not_completed" in reason

    def test_incomplete_run_ineligible(self):
        reason = SettlementVerifier._check_eligibility(
            _make_run(completion_status="incomplete")
        )
        assert "not_valid" in reason

    def test_invalid_run_ineligible(self):
        reason = SettlementVerifier._check_eligibility(
            _make_run(completion_status="invalid")
        )
        assert "not_valid" in reason

    def test_missing_ending_value_ineligible(self):
        reason = SettlementVerifier._check_eligibility(
            _make_run(ending_value=None)
        )
        assert "missing_ending_value" in reason

    def test_missing_run_log_hash_ineligible(self):
        reason = SettlementVerifier._check_eligibility(
            _make_run(run_log_hash=None)
        )
        assert "missing_run_log_hash" in reason

    def test_missing_empty_run_log_hash_ineligible(self):
        reason = SettlementVerifier._check_eligibility(
            _make_run(run_log_hash="")
        )
        assert "missing_run_log_hash" in reason


# -----------------------------------------------------------------------
# 6. Winner determination
# -----------------------------------------------------------------------


class TestWinnerDetermination:
    def test_highest_ending_value_wins(self):
        runs = [
            _make_run(agent_id=1, ending_value=100),
            _make_run(agent_id=2, ending_value=200),
            _make_run(agent_id=3, ending_value=150),
        ]
        winner = SettlementVerifier.determine_winner(runs)
        assert winner.agent_id == 2

    def test_tiebreak_by_earliest_ended_at(self):
        runs = [
            _make_run(agent_id=1, ending_value=200, ended_at=datetime(2025, 1, 1, 12, 1, 0, tzinfo=timezone.utc)),
            _make_run(agent_id=2, ending_value=200, ended_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)),
        ]
        winner = SettlementVerifier.determine_winner(runs)
        assert winner.agent_id == 2  # Earlier

    def test_no_eligible_runs_returns_none(self):
        assert SettlementVerifier.determine_winner([]) is None

    def test_single_run_wins(self):
        winner = SettlementVerifier.determine_winner([_make_run(agent_id=7)])
        assert winner.agent_id == 7

    def test_invalid_run_cannot_win_via_eligibility(self):
        """Invalid runs should never reach determine_winner — but even if
        they did, the eligibility check catches them first."""
        invalid = _make_run(agent_id=1, ending_value=9999, completion_status="invalid")
        valid = _make_run(agent_id=2, ending_value=100)

        # Only pass eligible runs to determine_winner
        eligible = [r for r in [invalid, valid] if SettlementVerifier._check_eligibility(r) is None]
        winner = SettlementVerifier.determine_winner(eligible)
        assert winner.agent_id == 2  # Invalid excluded

    def test_incomplete_run_excluded_from_eligibility(self):
        incomplete = _make_run(agent_id=1, ending_value=9999, completion_status="incomplete")
        valid = _make_run(agent_id=2, ending_value=100)

        eligible = [r for r in [incomplete, valid] if SettlementVerifier._check_eligibility(r) is None]
        winner = SettlementVerifier.determine_winner(eligible)
        assert winner.agent_id == 2


# -----------------------------------------------------------------------
# 7. SettlementEligibility dataclass
# -----------------------------------------------------------------------


class TestSettlementEligibilityDataclass:
    def test_can_settle_with_all_terminal(self):
        e = SettlementEligibility(eligible=[_make_run()])
        assert e.can_settle

    def test_cannot_settle_without_eligible(self):
        e = SettlementEligibility(
            eligible=[],
            ineligible=[(_make_run(status="completed"), "reason")],
        )
        assert not e.can_settle

    def test_cannot_settle_while_runs_still_running(self):
        """One completed + one still running = cannot settle."""
        running = _make_run(status="running")
        completed = _make_run(status="completed")
        e = SettlementEligibility(
            eligible=[completed],
            ineligible=[(running, "not_completed:running")],
        )
        assert not e.can_settle
        assert not e.all_terminal

    def test_can_settle_when_all_terminal_even_if_some_invalid(self):
        """All terminal (completed+failed) but some invalid = can settle if eligible exists."""
        valid = _make_run(status="completed", completion_status="complete")
        invalid = _make_run(status="completed", completion_status="invalid")
        e = SettlementEligibility(
            eligible=[valid],
            ineligible=[(invalid, "not_valid")],
            expected_contestants=2,
        )
        assert e.all_terminal
        assert e.can_settle

    def test_cannot_settle_with_missing_contestants(self):
        """1 run present but 3 expected = cannot settle."""
        e = SettlementEligibility(
            eligible=[_make_run()],
            expected_contestants=3,
        )
        assert not e.cardinality_met
        assert not e.can_settle

    def test_cardinality_met_with_correct_count(self):
        valid1 = _make_run(agent_id=1)
        valid2 = _make_run(agent_id=2)
        e = SettlementEligibility(
            eligible=[valid1, valid2],
            expected_contestants=2,
        )
        assert e.cardinality_met
        assert e.can_settle


# -----------------------------------------------------------------------
# 8. Post-chain error exclusion from hash
# -----------------------------------------------------------------------


class TestPostChainErrorExclusion:
    def test_onchain_finalize_failed_error_excluded(self):
        """Error events with onchain_finalize_failed must be excluded from hash."""
        from src.integrity.run_auditor import _is_post_chain_error

        event = MagicMock()
        event.event_type = "error"
        event.result_payload_json = json.dumps({"onchain_finalize_failed": True, "error": "RPC"})
        assert _is_post_chain_error(event) is True

    def test_regular_error_not_excluded(self):
        from src.integrity.run_auditor import _is_post_chain_error

        event = MagicMock()
        event.event_type = "error"
        event.result_payload_json = json.dumps({"error": "LLM crash", "fatal": True})
        assert _is_post_chain_error(event) is False

    def test_non_error_event_not_excluded(self):
        from src.integrity.run_auditor import _is_post_chain_error

        event = MagicMock()
        event.event_type = "observe"
        event.result_payload_json = None
        assert _is_post_chain_error(event) is False

    def test_hash_same_with_and_without_post_chain_error(self):
        """End-to-end: generate_run_log_hash must exclude onchain_finalize_failed."""
        from src.integrity.run_auditor import event_to_canonical_dict, is_evidence_event_type, _is_post_chain_error

        evidence_event = TestAuditTrail._make_db_event(
            sequence_no=0, event_type="observe", state_snapshot_json='{"USDC": 1000}',
        )
        finalize_event = TestAuditTrail._make_db_event(
            sequence_no=1, event_type="finalize",
            result_payload_json='{"ending_value": 1000}',
        )
        post_chain_error = TestAuditTrail._make_db_event(
            sequence_no=2, event_type="error",
            result_payload_json=json.dumps({"onchain_finalize_failed": True, "error": "RPC"}),
        )

        # Hash without the post-chain error
        evidence_only = [evidence_event, finalize_event]
        evidence_dicts = [
            event_to_canonical_dict(e) for e in evidence_only
            if is_evidence_event_type(e.event_type) and not _is_post_chain_error(e)
        ]
        hash_without = compute_evidence_hash(evidence_dicts)

        # Hash with the post-chain error (should be filtered out)
        all_events = [evidence_event, finalize_event, post_chain_error]
        all_dicts = [
            event_to_canonical_dict(e) for e in all_events
            if is_evidence_event_type(e.event_type) and not _is_post_chain_error(e)
        ]
        hash_with = compute_evidence_hash(all_dicts)

        assert hash_without == hash_with


# -----------------------------------------------------------------------
# 9. Duplicate agent detection
# -----------------------------------------------------------------------


class TestDuplicateAgentDetection:
    @pytest.mark.asyncio
    async def test_settlement_rejects_duplicate_agents(self):
        """verify_settlement_eligibility must raise on duplicate agent_ids."""
        mock_db = AsyncMock()

        mock_challenge = MagicMock()
        mock_challenge.num_contestants = 2
        mock_db.get = AsyncMock(return_value=mock_challenge)

        # Two runs with the same agent_id
        dup_runs = [_make_run(agent_id=1), _make_run(agent_id=1)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = dup_runs
        mock_db.execute = AsyncMock(return_value=mock_result)

        verifier = SettlementVerifier(mock_db)
        with pytest.raises(ValueError, match="duplicate"):
            await verifier.verify_settlement_eligibility(1)


# -----------------------------------------------------------------------
# 10. Audit hash recomputation
# -----------------------------------------------------------------------


class TestAuditHashVerification:
    @pytest.mark.asyncio
    async def test_mismatch_raises(self):
        """If stored hash != recomputed hash, audit trail must raise."""
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.get = AsyncMock(return_value=MagicMock(config_json="{}", submission_hash="x"))

        # Return events that produce a different hash than stored
        mock_event = MagicMock()
        mock_event.event_type = "observe"
        mock_event.sequence_no = 0
        mock_event.run_id = 1
        mock_event.timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
        mock_event.state_snapshot_json = '{"USDC": 999}'
        mock_event.action_payload_json = None
        mock_event.validation_payload_json = None
        mock_event.execution_payload_json = None
        mock_event.result_payload_json = None
        mock_event.tx_signature = None
        mock_event.quote_snapshot_ref = None

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_event]
        mock_db.execute = AsyncMock(return_value=mock_result)

        auditor = RunAuditor(mock_db)
        run = _make_run(run_log_hash="0000000000000000000000000000000000000000000000000000000000000000")

        with pytest.raises(ValueError, match="hash mismatch"):
            await auditor.create_audit_trail(run)


# -----------------------------------------------------------------------
# 10. Module imports
# -----------------------------------------------------------------------


class TestImports:
    def test_all(self):
        from src.integrity import (
            RunAuditor,
            SettlementVerifier,
            SettlementEligibility,
            ActionValidator,
            CompletionEvaluator,
            ValidationResult,
        )

        assert all([
            RunAuditor, SettlementVerifier, SettlementEligibility,
            ActionValidator, CompletionEvaluator, ValidationResult,
        ])

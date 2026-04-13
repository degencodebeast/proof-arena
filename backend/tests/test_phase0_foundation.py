"""Phase 0 Foundation tests.

Covers all 6 test categories from Task 1:
1. Schema validation (Pydantic)
2. Migration sanity (Alembic offline SQL generation)
3. Protocol compliance (stub implementations)
4. Import tests (all modules importable)
5. Version constant tests
6. Status enum tests (lifecycle vs completion)
"""

import json

import pytest
from pydantic import ValidationError


# -----------------------------------------------------------------------
# 1. Schema validation — AgentAction with valid/invalid inputs
# -----------------------------------------------------------------------


class TestAgentAction:
    def test_valid_execute_swap(self):
        from src.db.schemas import AgentAction, AgentActionType

        action = AgentAction(
            type=AgentActionType.EXECUTE_SWAP,
            params={"quote_id": "abc-123", "max_slippage_bps": 100},
        )
        assert action.type == AgentActionType.EXECUTE_SWAP
        assert action.params["quote_id"] == "abc-123"

    def test_valid_wait(self):
        from src.db.schemas import AgentAction, AgentActionType

        action = AgentAction(
            type=AgentActionType.WAIT,
            params={"seconds": 30},
        )
        assert action.type == AgentActionType.WAIT
        assert action.params["seconds"] == 30

    def test_valid_finish(self):
        from src.db.schemas import AgentAction, AgentActionType

        action = AgentAction(
            type=AgentActionType.FINISH,
            params={},
        )
        assert action.type == AgentActionType.FINISH

    def test_invalid_action_type(self):
        from src.db.schemas import AgentAction

        with pytest.raises(ValidationError):
            AgentAction(type="INVALID_TYPE", params={})

    def test_execute_swap_missing_quote_id(self):
        from src.db.schemas import AgentAction, AgentActionType

        with pytest.raises(ValidationError):
            AgentAction(
                type=AgentActionType.EXECUTE_SWAP,
                params={"max_slippage_bps": 100},
            )

    def test_execute_swap_slippage_too_high(self):
        from src.db.schemas import AgentAction, AgentActionType

        with pytest.raises(ValidationError):
            AgentAction(
                type=AgentActionType.EXECUTE_SWAP,
                params={"quote_id": "x", "max_slippage_bps": 501},
            )

    def test_wait_seconds_out_of_range(self):
        from src.db.schemas import AgentAction, AgentActionType

        with pytest.raises(ValidationError):
            AgentAction(
                type=AgentActionType.WAIT,
                params={"seconds": 0},
            )
        with pytest.raises(ValidationError):
            AgentAction(
                type=AgentActionType.WAIT,
                params={"seconds": 61},
            )

    def test_finish_with_params_rejected(self):
        from src.db.schemas import AgentAction, AgentActionType

        with pytest.raises(ValidationError):
            AgentAction(
                type=AgentActionType.FINISH,
                params={"extra": "not allowed"},
            )

    def test_action_is_frozen(self):
        from src.db.schemas import AgentAction, AgentActionType

        action = AgentAction(
            type=AgentActionType.FINISH,
            params={},
        )
        with pytest.raises(ValidationError):
            action.type = AgentActionType.WAIT


# -----------------------------------------------------------------------
# 2. Request/response schema validation
# -----------------------------------------------------------------------


class TestRequestSchemas:
    def test_strategy_submit_valid(self):
        from src.db.schemas import StrategySubmitRequest

        req = StrategySubmitRequest(
            agent_name="TestBot",
            system_prompt="Execute swaps efficiently.",
        )
        assert req.agent_name == "TestBot"

    def test_strategy_submit_name_too_long(self):
        from src.db.schemas import StrategySubmitRequest

        with pytest.raises(ValidationError):
            StrategySubmitRequest(
                agent_name="x" * 65,
                system_prompt="test",
            )

    def test_strategy_submit_empty_prompt_rejected(self):
        from src.db.schemas import StrategySubmitRequest

        with pytest.raises(ValidationError):
            StrategySubmitRequest(
                agent_name="Bot",
                system_prompt="",
            )

    def test_challenge_create_valid(self):
        from src.db.schemas import ChallengeCreateRequest

        req = ChallengeCreateRequest(
            starting_usdc=1_000_000_000,
            swap_intents=["SOL"],
            contestant_agent_ids=[1, 2],
        )
        assert req.starting_usdc == 1_000_000_000

    def test_challenge_create_zero_usdc_rejected(self):
        from src.db.schemas import ChallengeCreateRequest

        with pytest.raises(ValidationError):
            ChallengeCreateRequest(
                starting_usdc=0,
                swap_intents=["SOL"],
                contestant_agent_ids=[1],
            )

    def test_leaderboard_entry_from_attributes(self):
        from src.db.schemas import LeaderboardEntry

        entry = LeaderboardEntry(
            agent_id=1,
            display_name="Bot",
            score=85.5,
            rank_version="rank_v1",
            wins=3,
            losses=1,
            completed_runs=4,
            invalid_runs=0,
        )
        assert entry.score == 85.5
        assert entry.twitter_handle is None


# -----------------------------------------------------------------------
# 3. Protocol compliance — stub implementations
# -----------------------------------------------------------------------


class TestProtocolCompliance:
    def test_agent_decision_provider_stub(self):
        from src.providers.base import AgentDecisionProvider
        from src.challenges.base import ChallengeState
        from src.db.schemas import AgentAction, AgentActionType

        class StubProvider:
            async def decide(self, state: ChallengeState) -> AgentAction:
                return AgentAction(type=AgentActionType.FINISH, params={})

        assert isinstance(StubProvider(), AgentDecisionProvider)

    def test_challenge_adapter_stub(self):
        from src.challenges.base import (
            ChallengeAdapter,
            ChallengeState,
            CompletionResult,
            QuoteOption,
            ScoreInputs,
        )

        class StubAdapter:
            async def build_initial_state(self, wallet_address: str) -> ChallengeState:
                return ChallengeState(
                    portfolio={"USDC": 1000},
                    completed_swaps=[],
                    required_swaps=["SOL"],
                    iterations_used=0,
                    elapsed_secs=0.0,
                    iteration_budget=20,
                    time_budget_secs=300,
                    status="active",
                )

            async def list_available_actions(self, state: ChallengeState) -> list[QuoteOption]:
                return []

            async def validate_completion(self, run) -> CompletionResult:
                return CompletionResult(status="complete")

            async def compute_score_inputs(self, run) -> ScoreInputs:
                return ScoreInputs(
                    completed_required_actions=True,
                    completion_rate=1.0,
                    invalid_run=False,
                    execution_quality=1.0,
                    ending_value_delta=0,
                    iterations_used=0,
                    time_used_secs=0.0,
                )

        assert isinstance(StubAdapter(), ChallengeAdapter)

    def test_action_validator_stub(self):
        from src.integrity import ActionValidator, ValidationResult

        class StubValidator:
            async def validate(self, action, state) -> ValidationResult:
                return ValidationResult(valid=True)

        assert isinstance(StubValidator(), ActionValidator)

    def test_non_conforming_class_rejected(self):
        from src.providers.base import AgentDecisionProvider

        class BadProvider:
            pass

        assert not isinstance(BadProvider(), AgentDecisionProvider)


# -----------------------------------------------------------------------
# 4. Import tests — all modules importable
# -----------------------------------------------------------------------


class TestImports:
    def test_import_providers(self):
        from src.providers import AgentDecisionProvider

        assert AgentDecisionProvider is not None

    def test_import_challenges(self):
        from src.challenges import (
            ChallengeAdapter,
            ChallengeState,
            CompletionResult,
            QuoteOption,
            ScoreInputs,
        )

        assert ChallengeAdapter is not None
        assert ChallengeState is not None
        assert CompletionResult is not None
        assert QuoteOption is not None
        assert ScoreInputs is not None

    def test_import_integrity(self):
        from src.integrity import ActionValidator, ValidationResult

        assert ActionValidator is not None
        assert ValidationResult is not None

    def test_import_schemas(self):
        from src.db.schemas import (
            AgentAction,
            AgentActionType,
            AgentStatus,
            ChallengeStatus,
            CompletionStatus,
            InvalidReason,
            ModerationStatus,
            RunEventType,
            RunStatus,
        )

        assert len(AgentActionType) == 3
        assert len(RunStatus) == 5
        assert len(CompletionStatus) == 3

    def test_import_models(self):
        from src.db.models import (
            Agent,
            Base,
            Challenge,
            RankSnapshot,
            Run,
            RunEvent,
            VerificationArtifact,
        )

        tables = list(Base.metadata.tables.keys())
        assert len(tables) == 6
        assert "agents" in tables
        assert "runs" in tables
        assert "run_events" in tables
        assert "rank_snapshots" in tables
        assert "verification_artifacts" in tables

    def test_import_config(self):
        from src.config import (
            ACTION_SCHEMA_VERSION,
            APP_VERSION,
            CHALLENGE_VERSION,
            EVIDENCE_SCHEMA_VERSION,
            RANK_VERSION,
            Settings,
        )

        assert APP_VERSION is not None
        assert Settings is not None


# -----------------------------------------------------------------------
# 5. Version constant tests — match VERSIONING.md format
# -----------------------------------------------------------------------


class TestVersionConstants:
    def test_app_version_is_semver(self):
        from src.config import APP_VERSION

        parts = APP_VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_challenge_version_format(self):
        from src.config import CHALLENGE_VERSION

        assert CHALLENGE_VERSION == "swap_execution_v1"
        assert "_v" in CHALLENGE_VERSION

    def test_rank_version_format(self):
        from src.config import RANK_VERSION

        assert RANK_VERSION == "rank_v1"
        assert "_v" in RANK_VERSION

    def test_evidence_schema_version_format(self):
        from src.config import EVIDENCE_SCHEMA_VERSION

        assert EVIDENCE_SCHEMA_VERSION == "evidence_v1"

    def test_action_schema_version_format(self):
        from src.config import ACTION_SCHEMA_VERSION

        assert ACTION_SCHEMA_VERSION == "agent_action_v1"

    def test_api_version(self):
        from src.config import API_VERSION

        assert API_VERSION == "v1"

    def test_all_versions_non_empty(self):
        from src.config import (
            ACTION_SCHEMA_VERSION,
            API_VERSION,
            APP_VERSION,
            CHALLENGE_VERSION,
            EVIDENCE_SCHEMA_VERSION,
            RANK_VERSION,
        )

        for v in [
            APP_VERSION,
            API_VERSION,
            CHALLENGE_VERSION,
            RANK_VERSION,
            EVIDENCE_SCHEMA_VERSION,
            ACTION_SCHEMA_VERSION,
        ]:
            assert v and len(v) > 0


# -----------------------------------------------------------------------
# 6. Status enum tests — lifecycle vs completion are distinct
# -----------------------------------------------------------------------


class TestStatusEnums:
    def test_run_status_values(self):
        from src.db.schemas import RunStatus

        expected = {"pending", "running", "completed", "failed", "timeout"}
        actual = {s.value for s in RunStatus}
        assert actual == expected

    def test_completion_status_values(self):
        from src.db.schemas import CompletionStatus

        expected = {"complete", "incomplete", "invalid"}
        actual = {s.value for s in CompletionStatus}
        assert actual == expected

    def test_lifecycle_and_completion_are_distinct(self):
        from src.db.schemas import CompletionStatus, RunStatus

        lifecycle_values = {s.value for s in RunStatus}
        completion_values = {s.value for s in CompletionStatus}
        assert lifecycle_values.isdisjoint(completion_values), (
            "Lifecycle and completion status values must not overlap"
        )

    def test_invalid_reason_values(self):
        from src.db.schemas import InvalidReason

        expected = {
            "incomplete_required_actions",
            "invalid_action_attempts_exceeded",
            "stale_quote_execution_failed",
            "timeout_before_completion",
            "flattening_failed",
            "execution_error",
        }
        actual = {r.value for r in InvalidReason}
        assert actual == expected

    def test_challenge_status_values(self):
        from src.db.schemas import ChallengeStatus

        expected = {"pending", "active", "settling", "completed", "cancelled"}
        actual = {s.value for s in ChallengeStatus}
        assert actual == expected

    def test_run_event_type_values(self):
        from src.db.schemas import RunEventType

        assert "observe" in {e.value for e in RunEventType}
        assert "decide" in {e.value for e in RunEventType}
        assert "validate" in {e.value for e in RunEventType}
        assert "execute" in {e.value for e in RunEventType}


# -----------------------------------------------------------------------
# 7. Model field verification — all plan fields present
# -----------------------------------------------------------------------


class TestModelFields:
    def test_run_has_separate_status_and_completion(self):
        from src.db.models import Base

        run_table = Base.metadata.tables["runs"]
        col_names = {c.name for c in run_table.columns}
        assert "status" in col_names
        assert "completion_status" in col_names
        assert "invalid_reason" in col_names

    def test_run_has_all_version_fields(self):
        """Per VERSIONING.md: every Run must persist app_version,
        challenge_type, challenge_version, action_schema_version,
        evidence_schema_version."""
        from src.db.models import Base

        run_table = Base.metadata.tables["runs"]
        col_names = {c.name for c in run_table.columns}
        assert "app_version" in col_names
        assert "challenge_type" in col_names
        assert "challenge_version" in col_names
        assert "action_schema_version" in col_names
        assert "evidence_schema_version" in col_names

    def test_run_has_iterations_used(self):
        """iterations_used is part of the canonical run record per the
        implementation plan and on-chain finalize_run instruction."""
        from src.db.models import Base

        run_table = Base.metadata.tables["runs"]
        col_names = {c.name for c in run_table.columns}
        assert "iterations_used" in col_names

    def test_run_has_benchmark_wallet_fields(self):
        from src.db.models import Base

        run_table = Base.metadata.tables["runs"]
        col_names = {c.name for c in run_table.columns}
        assert "benchmark_wallet_address" in col_names
        assert "benchmark_wallet_ref" in col_names

    def test_run_has_value_fields(self):
        from src.db.models import Base

        run_table = Base.metadata.tables["runs"]
        col_names = {c.name for c in run_table.columns}
        assert "starting_value" in col_names
        assert "ending_value" in col_names
        assert "run_log_hash" in col_names
        assert "score_inputs_json" in col_names

    def test_agent_has_all_plan_fields(self):
        from src.db.models import Base

        agent_table = Base.metadata.tables["agents"]
        col_names = {c.name for c in agent_table.columns}
        required = {
            "agent_id", "privy_user_id", "owner_wallet", "display_name",
            "submission_type", "submission_hash", "system_prompt",
            "config_json", "metadata_ref", "provider_type",
            "provider_config_json", "twitter_handle", "onchain_address",
            "status", "moderation_status", "created_at",
        }
        assert required.issubset(col_names), f"Missing: {required - col_names}"

    def test_challenge_has_all_plan_fields(self):
        from src.db.models import Base

        table = Base.metadata.tables["challenges"]
        col_names = {c.name for c in table.columns}
        required = {
            "challenge_id", "challenge_type", "challenge_version",
            "llm_provider", "llm_model", "config_json", "instance_seed",
            "status", "num_contestants", "num_finalized",
            "winner_agent_id", "onchain_address",
            "created_at", "started_at", "ended_at",
        }
        assert required.issubset(col_names), f"Missing: {required - col_names}"

    def test_run_event_has_separate_payload_columns(self):
        from src.db.models import Base

        table = Base.metadata.tables["run_events"]
        col_names = {c.name for c in table.columns}
        required = {
            "event_id", "run_id", "sequence_no", "event_type", "timestamp",
            "state_snapshot_json", "action_payload_json",
            "validation_payload_json", "execution_payload_json",
            "result_payload_json", "tx_signature", "quote_snapshot_ref",
        }
        assert required.issubset(col_names), f"Missing: {required - col_names}"

    def test_rank_snapshot_has_all_fields(self):
        from src.db.models import Base

        table = Base.metadata.tables["rank_snapshots"]
        col_names = {c.name for c in table.columns}
        required = {
            "snapshot_id", "agent_id", "rank_version", "app_version",
            "score", "score_inputs_json", "score_breakdown_json",
            "wins", "losses", "completed_runs", "invalid_runs",
            "computed_at",
        }
        assert required.issubset(col_names), f"Missing: {required - col_names}"

    def test_verification_artifact_fields(self):
        from src.db.models import Base

        table = Base.metadata.tables["verification_artifacts"]
        col_names = {c.name for c in table.columns}
        required = {
            "artifact_id", "run_id", "artifact_type",
            "uri_or_ref", "content_hash", "created_at",
        }
        assert required.issubset(col_names), f"Missing: {required - col_names}"


# -----------------------------------------------------------------------
# 8. Migration sanity — verify SQL generates without errors
# -----------------------------------------------------------------------


class TestMigrationSanity:
    def test_offline_sql_generation(self, capsys):
        """Verify the migration can generate SQL in offline mode."""
        from alembic.config import Config
        from alembic import command
        import io

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", "postgresql+asyncpg://x:x@localhost/x")

        buf = io.StringIO()
        alembic_cfg.attributes["output_buffer"] = buf
        command.upgrade(alembic_cfg, "head", sql=True)
        sql = buf.getvalue()

        # The output buffer may be empty if alembic writes to stdout instead
        if not sql:
            captured = capsys.readouterr()
            sql = captured.out

        assert "agents" in sql
        assert "challenges" in sql
        assert "runs" in sql
        assert "run_events" in sql
        assert "rank_snapshots" in sql
        assert "verification_artifacts" in sql
        assert "completion_status" in sql
        assert "action_schema_version" in sql
        assert "evidence_schema_version" in sql


# -----------------------------------------------------------------------
# 9. ChallengeState and ScoreInputs dataclass tests
# -----------------------------------------------------------------------


class TestDataclasses:
    def test_challenge_state_creation(self):
        from src.challenges.base import ChallengeState

        state = ChallengeState(
            portfolio={"USDC": 1_000_000_000},
            completed_swaps=[],
            required_swaps=["SOL"],
            iterations_used=0,
            elapsed_secs=0.0,
            iteration_budget=20,
            time_budget_secs=300,
            status="active",
        )
        assert state.portfolio["USDC"] == 1_000_000_000
        assert state.status == "active"

    def test_score_inputs_creation(self):
        from src.challenges.base import ScoreInputs

        inputs = ScoreInputs(
            completed_required_actions=True,
            completion_rate=1.0,
            invalid_run=False,
            execution_quality=0.95,
            ending_value_delta=4_500_000,
            iterations_used=8,
            time_used_secs=180.0,
        )
        assert inputs.execution_quality == 0.95
        assert inputs.completed_required_actions is True

    def test_completion_result_creation(self):
        from src.challenges.base import CompletionResult

        result = CompletionResult(status="complete")
        assert result.status == "complete"
        assert result.reason is None

        result2 = CompletionResult(
            status="incomplete",
            reason="incomplete_required_actions",
        )
        assert result2.reason == "incomplete_required_actions"

"""Task 4: Backend Services tests.

Covers:
1. Settings loading and defaults
2. FastAPI health/bootstrap
3. Deterministic submission hashing
4. PDA derivation consistency with Anchor program
5. SolanaService initialization (with Provider/Wallet)
6. AgentArenaClient instruction construction with mocks
7. Strategy service — honest ownership model, failure states
8. Challenge service — failure handling, lifecycle
9. Auth dependencies
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# -----------------------------------------------------------------------
# 1. Settings and config
# -----------------------------------------------------------------------


class TestSettings:
    def test_default_values(self):
        from src.config import settings

        assert settings.APP_VERSION == "0.1.0"
        assert settings.API_VERSION == "v1"
        assert settings.CHALLENGE_VERSION == "swap_execution_v1"
        assert settings.RANK_VERSION == "rank_v1"
        assert settings.EVIDENCE_SCHEMA_VERSION == "evidence_v1"
        assert settings.ACTION_SCHEMA_VERSION == "agent_action_v1"

    def test_database_url_default(self):
        from src.config import settings

        assert "postgresql+asyncpg" in settings.DATABASE_URL

    def test_version_constants_module_level(self):
        from src.config import (
            ACTION_SCHEMA_VERSION,
            APP_VERSION,
            CHALLENGE_VERSION,
            EVIDENCE_SCHEMA_VERSION,
            RANK_VERSION,
        )

        assert APP_VERSION == "0.1.0"
        assert CHALLENGE_VERSION == "swap_execution_v1"
        assert RANK_VERSION == "rank_v1"
        assert EVIDENCE_SCHEMA_VERSION == "evidence_v1"
        assert ACTION_SCHEMA_VERSION == "agent_action_v1"


# -----------------------------------------------------------------------
# 2. FastAPI health/bootstrap
# -----------------------------------------------------------------------


class TestFastAPIBootstrap:
    def test_health_endpoint(self):
        from src.main import app

        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"
        assert data["api_version"] == "v1"

    def test_app_metadata(self):
        from src.main import app

        assert app.title == "Agent Arena"
        assert app.version == "0.1.0"


# -----------------------------------------------------------------------
# 3. Deterministic submission hashing
# -----------------------------------------------------------------------


class TestSubmissionHashing:
    def test_deterministic(self):
        from src.services.strategy_service import StrategyService

        h1 = StrategyService.compute_submission_hash("prompt", {"k": "v"})
        h2 = StrategyService.compute_submission_hash("prompt", {"k": "v"})
        assert h1 == h2

    def test_changes_with_prompt(self):
        from src.services.strategy_service import StrategyService

        h1 = StrategyService.compute_submission_hash("A", {})
        h2 = StrategyService.compute_submission_hash("B", {})
        assert h1 != h2

    def test_changes_with_config(self):
        from src.services.strategy_service import StrategyService

        h1 = StrategyService.compute_submission_hash("p", {"a": 1})
        h2 = StrategyService.compute_submission_hash("p", {"a": 2})
        assert h1 != h2

    def test_is_sha256_hex(self):
        from src.services.strategy_service import StrategyService

        h = StrategyService.compute_submission_hash("test", {})
        assert len(h) == 64
        int(h, 16)

    def test_ignores_key_order(self):
        from src.services.strategy_service import StrategyService

        h1 = StrategyService.compute_submission_hash("p", {"b": 2, "a": 1})
        h2 = StrategyService.compute_submission_hash("p", {"a": 1, "b": 2})
        assert h1 == h2

    def test_strips_whitespace(self):
        from src.services.strategy_service import StrategyService

        h1 = StrategyService.compute_submission_hash("  test  ", {})
        h2 = StrategyService.compute_submission_hash("test", {})
        assert h1 == h2

    def test_round_trip_verification(self):
        from src.services.strategy_service import StrategyService

        prompt = "Execute swaps."
        config = {"risk": "low"}
        h = StrategyService.compute_submission_hash(prompt, config)

        svc = StrategyService(db=MagicMock())
        agent = MagicMock()
        agent.submission_hash = h
        assert svc.verify_submission_hash(agent, prompt, config)

    def test_mismatch_detected(self):
        from src.services.strategy_service import StrategyService

        svc = StrategyService(db=MagicMock())
        agent = MagicMock()
        agent.submission_hash = "wrong"
        assert not svc.verify_submission_hash(agent, "p", {})


# -----------------------------------------------------------------------
# 4. PDA derivation consistency
# -----------------------------------------------------------------------


class TestPDADerivation:
    def test_config_pda(self):
        from solders.pubkey import Pubkey
        from src.chain.program_client import CONFIG_SEED

        pda, bump = Pubkey.find_program_address(
            [CONFIG_SEED], Pubkey.new_unique()
        )
        assert pda != Pubkey.default()

    def test_strategy_pda_includes_owner(self):
        from solders.pubkey import Pubkey
        from src.chain.program_client import STRATEGY_SEED

        owner = Pubkey.new_unique()
        pda, _ = Pubkey.find_program_address(
            [STRATEGY_SEED, bytes(owner), (1).to_bytes(8, "little")],
            Pubkey.new_unique(),
        )
        assert pda != Pubkey.default()

    def test_strategy_pda_differs_by_owner(self):
        from solders.pubkey import Pubkey
        from src.chain.program_client import STRATEGY_SEED

        pid = Pubkey.new_unique()
        pda1, _ = Pubkey.find_program_address(
            [STRATEGY_SEED, bytes(Pubkey.new_unique()), (1).to_bytes(8, "little")], pid
        )
        pda2, _ = Pubkey.find_program_address(
            [STRATEGY_SEED, bytes(Pubkey.new_unique()), (1).to_bytes(8, "little")], pid
        )
        assert pda1 != pda2

    def test_seeds_match_anchor_constants(self):
        from src.chain.program_client import (
            AGENT_RANK_SEED, CHALLENGE_SEED, CONFIG_SEED, RUN_SEED, STRATEGY_SEED,
        )

        assert CONFIG_SEED == b"config"
        assert STRATEGY_SEED == b"strategy"
        assert CHALLENGE_SEED == b"challenge"
        assert RUN_SEED == b"run"
        assert AGENT_RANK_SEED == b"agent_rank"


# -----------------------------------------------------------------------
# 5. SolanaService initialization
# -----------------------------------------------------------------------


class TestSolanaService:
    def test_init_without_keypair(self):
        from src.services.solana_service import SolanaService

        svc = SolanaService(
            rpc_url="https://api.devnet.solana.com",
            authority_keypair_path="/nonexistent",
        )
        assert svc.authority is None
        assert svc.authority_pubkey is None
        assert svc.wallet is None
        assert svc.provider is None
        assert not svc.is_ready

    def test_init_with_rpc_url(self):
        from src.services.solana_service import SolanaService

        svc = SolanaService(rpc_url="https://api.devnet.solana.com")
        assert svc.rpc_url == "https://api.devnet.solana.com"
        assert svc.client is not None

    def test_init_with_keypair(self, tmp_path):
        """Test that a valid keypair file creates Provider and Wallet."""
        from solders.keypair import Keypair
        from src.services.solana_service import SolanaService

        kp = Keypair()
        kp_path = tmp_path / "test_keypair.json"
        kp_path.write_text(json.dumps(list(bytes(kp))))

        svc = SolanaService(
            rpc_url="https://api.devnet.solana.com",
            authority_keypair_path=str(kp_path),
        )
        assert svc.authority is not None
        assert svc.authority_pubkey == kp.pubkey()
        assert svc.wallet is not None
        assert svc.provider is not None
        assert svc.is_ready

    def test_context_manager(self):
        """SolanaService supports async context management."""
        from src.services.solana_service import SolanaService

        svc = SolanaService(rpc_url="https://api.devnet.solana.com")
        assert hasattr(svc, "__aenter__")
        assert hasattr(svc, "__aexit__")


# -----------------------------------------------------------------------
# 6. AgentArenaClient instruction construction
# -----------------------------------------------------------------------


class TestAgentArenaClientConstruction:
    """Test that instruction calls build correct Context arguments."""

    def _make_mock_program(self):
        """Create a mock Program with rpc dict that captures calls."""
        mock_program = MagicMock()
        mock_rpc = {}

        def make_rpc_fn(name):
            fn = AsyncMock(return_value="mock_tx_sig")
            mock_rpc[name] = fn
            return fn

        for ix in [
            "initialize", "register_strategy", "create_challenge",
            "create_run", "start_challenge", "finalize_run",
            "settle_challenge", "update_agent_rank",
        ]:
            make_rpc_fn(ix)

        mock_program.rpc = mock_rpc
        return mock_program, mock_rpc

    @pytest.mark.asyncio
    async def test_initialize_builds_correct_context(self):
        from anchorpy import Context
        from solders.pubkey import Pubkey
        from src.chain.program_client import AgentArenaClient, CONFIG_SEED

        mock_program, mock_rpc = self._make_mock_program()

        client = AgentArenaClient.__new__(AgentArenaClient)
        client.program_id = Pubkey.new_unique()
        client.program = mock_program
        client.provider = MagicMock()
        client.provider.wallet.public_key = Pubkey.new_unique()

        await client.initialize()

        mock_rpc["initialize"].assert_called_once()
        call_kwargs = mock_rpc["initialize"].call_args
        ctx = call_kwargs.kwargs["ctx"]
        assert isinstance(ctx, Context)
        assert "config" in ctx.accounts
        assert "admin" in ctx.accounts
        assert "system_program" in ctx.accounts

    @pytest.mark.asyncio
    async def test_register_strategy_requires_owner_keypair(self):
        """register_strategy must take an owner_keypair, not use authority."""
        from anchorpy import Context
        from solders.keypair import Keypair
        from solders.pubkey import Pubkey
        from src.chain.program_client import AgentArenaClient

        mock_program, mock_rpc = self._make_mock_program()

        client = AgentArenaClient.__new__(AgentArenaClient)
        client.program_id = Pubkey.new_unique()
        client.program = mock_program
        client.provider = MagicMock()
        client.provider.wallet.public_key = Pubkey.new_unique()

        owner = Keypair()
        await client.register_strategy(
            agent_id=1,
            agent_name="Test",
            submission_hash=b"\x00" * 32,
            metadata_ref="",
            owner_keypair=owner,
        )

        call_kwargs = mock_rpc["register_strategy"].call_args
        ctx = call_kwargs.kwargs["ctx"]
        # Owner in accounts must be the provided keypair, not authority
        assert ctx.accounts["owner"] == owner.pubkey()
        # Owner must be in signers
        assert owner in ctx.signers

    @pytest.mark.asyncio
    async def test_register_strategy_owner_is_not_authority(self):
        """Backend authority must NOT be used as strategy owner."""
        from solders.keypair import Keypair
        from solders.pubkey import Pubkey
        from src.chain.program_client import AgentArenaClient

        mock_program, mock_rpc = self._make_mock_program()

        client = AgentArenaClient.__new__(AgentArenaClient)
        client.program_id = Pubkey.new_unique()
        client.program = mock_program
        client.provider = MagicMock()
        authority_pk = Pubkey.new_unique()
        client.provider.wallet.public_key = authority_pk

        owner = Keypair()
        await client.register_strategy(
            agent_id=1,
            agent_name="Test",
            submission_hash=b"\x00" * 32,
            metadata_ref="",
            owner_keypair=owner,
        )

        ctx = mock_rpc["register_strategy"].call_args.kwargs["ctx"]
        # Owner account is the owner keypair, NOT the authority
        assert ctx.accounts["owner"] != authority_pk
        assert ctx.accounts["owner"] == owner.pubkey()

    @pytest.mark.asyncio
    async def test_create_challenge_includes_config_account(self):
        from solders.pubkey import Pubkey
        from src.chain.program_client import AgentArenaClient

        mock_program, mock_rpc = self._make_mock_program()

        client = AgentArenaClient.__new__(AgentArenaClient)
        client.program_id = Pubkey.new_unique()
        client.program = mock_program
        client.provider = MagicMock()
        client.provider.wallet.public_key = Pubkey.new_unique()

        await client.create_challenge(
            challenge_id=1,
            challenge_version=1,
            starting_usdc=100_000_000,
            usdc_mint=Pubkey.default(),
            max_slippage_bps=100,
            iteration_budget=20,
            time_budget_secs=300,
            num_contestants=2,
        )

        ctx = mock_rpc["create_challenge"].call_args.kwargs["ctx"]
        assert "config" in ctx.accounts
        assert "challenge_account" in ctx.accounts
        assert "authority" in ctx.accounts

    @pytest.mark.asyncio
    async def test_settle_challenge_passes_remaining_accounts(self):
        from solders.pubkey import Pubkey
        from src.chain.program_client import AgentArenaClient

        mock_program, mock_rpc = self._make_mock_program()

        client = AgentArenaClient.__new__(AgentArenaClient)
        client.program_id = Pubkey.new_unique()
        client.program = mock_program
        client.provider = MagicMock()
        client.provider.wallet.public_key = Pubkey.new_unique()

        run_pdas = [Pubkey.new_unique(), Pubkey.new_unique()]
        await client.settle_challenge(challenge_id=1, run_pdas=run_pdas)

        ctx = mock_rpc["settle_challenge"].call_args.kwargs["ctx"]
        assert len(ctx.remaining_accounts) == 2
        # anchorpy requires solders.instruction.AccountMeta, not dicts.
        # Prior to the Task 16 live-devnet fix this passed dicts and the
        # transaction blew up at construction time on real devnet. Assert
        # the fixed shape now.
        for ra in ctx.remaining_accounts:
            assert ra.is_signer is False
            assert ra.is_writable is False


# -----------------------------------------------------------------------
# 7. Strategy service — ownership model
# -----------------------------------------------------------------------


class TestStrategyServiceOwnership:
    @pytest.mark.asyncio
    async def test_register_creates_pending_onchain_status(self):
        """New strategy starts as pending_onchain, not active."""
        from src.services.strategy_service import StrategyService

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        svc = StrategyService(db=mock_db, program_client=None)
        agent = await svc.register_strategy(
            privy_user_id="user-1",
            owner_wallet="wallet-abc",
            display_name="TestBot",
            system_prompt="Execute swaps.",
        )

        # Should be pending_onchain, not active
        assert agent.status == "pending_onchain"
        assert agent.onchain_address is None

    @pytest.mark.asyncio
    async def test_register_does_not_call_onchain(self):
        """register_strategy must NOT attempt on-chain registration."""
        from src.services.strategy_service import StrategyService

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_program = MagicMock()

        svc = StrategyService(db=mock_db, program_client=mock_program)
        await svc.register_strategy(
            privy_user_id="user-1",
            owner_wallet="wallet-abc",
            display_name="TestBot",
            system_prompt="test",
        )

        # Program client should NOT have been called
        mock_program.register_strategy.assert_not_called()

    @pytest.mark.asyncio
    async def test_complete_onchain_transitions_to_active(self):
        """complete_onchain_registration transitions status correctly."""
        from src.services.strategy_service import StrategyService

        mock_agent = MagicMock()
        mock_agent.status = "pending_onchain"
        mock_agent.agent_id = 1

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=mock_agent)
        mock_db.commit = AsyncMock()

        svc = StrategyService(db=mock_db)
        result = await svc.complete_onchain_registration(
            agent_id=1,
            onchain_address="some_pda",
            tx_signature="some_sig",
        )

        assert result.status == "active"
        assert result.onchain_address == "some_pda"


# -----------------------------------------------------------------------
# 8. Challenge service — failure handling
# -----------------------------------------------------------------------


class TestChallengeServiceFailureHandling:
    @pytest.mark.asyncio
    async def test_start_challenge_raises_on_onchain_failure(self):
        """start_challenge must NOT transition Postgres if on-chain fails."""
        from src.services.challenge_service import ChallengeService, OnchainError

        mock_challenge = MagicMock()
        mock_challenge.challenge_id = 1
        mock_challenge.status = "pending"

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(
            return_value=mock_challenge
        )

        mock_program = MagicMock()
        mock_program.start_challenge = AsyncMock(
            side_effect=Exception("RPC error")
        )

        svc = ChallengeService(db=mock_db, program_client=mock_program)
        with pytest.raises(OnchainError):
            await svc.start_challenge(1)

        # Postgres must NOT have transitioned to active
        assert mock_challenge.status == "pending"

    @pytest.mark.asyncio
    async def test_create_challenge_marks_onchain_failed(self):
        """If on-chain create fails, Postgres status = onchain_failed."""
        from src.services.challenge_service import ChallengeService, OnchainError

        mock_db = AsyncMock()
        captured_challenge = None

        def capture_add(obj):
            nonlocal captured_challenge
            captured_challenge = obj
            obj.challenge_id = 1  # Simulate sequence assignment

        mock_db.add = MagicMock(side_effect=capture_add)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        mock_program = MagicMock()
        mock_program.create_challenge = AsyncMock(
            side_effect=Exception("RPC error")
        )

        svc = ChallengeService(db=mock_db, program_client=mock_program)
        with pytest.raises(OnchainError):
            await svc.create_challenge(contestant_agent_ids=[1, 2])

        # Postgres must record the failure status
        assert captured_challenge.status == "onchain_failed"

    @pytest.mark.asyncio
    async def test_start_without_program_client_raises(self):
        """start_challenge requires program client — no DB-only transitions."""
        from src.services.challenge_service import ChallengeService, OnchainError

        mock_db = AsyncMock()
        svc = ChallengeService(db=mock_db, program_client=None)
        with pytest.raises(OnchainError):
            await svc.start_challenge(1)

    @pytest.mark.asyncio
    async def test_create_challenge_without_program_raises(self):
        """create_challenge requires program client."""
        from src.services.challenge_service import ChallengeService, OnchainError

        mock_db = AsyncMock()
        svc = ChallengeService(db=mock_db, program_client=None)
        with pytest.raises(OnchainError):
            await svc.create_challenge(contestant_agent_ids=[1])

    @pytest.mark.asyncio
    async def test_create_run_defers_when_agent_has_no_onchain_address(self):
        """Run gets status=pending_onchain when agent lacks on-chain registration."""
        from src.services.challenge_service import ChallengeService

        mock_challenge = MagicMock()
        mock_challenge.challenge_id = 1
        mock_challenge.config_json = '{"starting_usdc": 100000000}'
        mock_challenge.challenge_type = "swap_execution"

        mock_agent = MagicMock()
        mock_agent.agent_id = 1
        mock_agent.onchain_address = None  # Not registered on-chain yet

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(
            return_value=mock_challenge
        )
        mock_db.get = AsyncMock(return_value=mock_agent)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        svc = ChallengeService(db=mock_db, program_client=None)
        run = await svc.create_run(1, 1)
        assert run.status == "pending_onchain"

    @pytest.mark.asyncio
    async def test_create_run_pending_when_agent_has_onchain(self):
        """Run gets status=pending when agent is registered on-chain."""
        from src.services.challenge_service import ChallengeService

        mock_challenge = MagicMock()
        mock_challenge.challenge_id = 1
        mock_challenge.config_json = '{"starting_usdc": 100000000}'
        mock_challenge.challenge_type = "swap_execution"

        mock_agent = MagicMock()
        mock_agent.agent_id = 1
        mock_agent.onchain_address = "SomePDA123"

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(
            return_value=mock_challenge
        )
        mock_db.get = AsyncMock(return_value=mock_agent)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        svc = ChallengeService(db=mock_db, program_client=None)
        run = await svc.create_run(1, 1)
        assert run.status == "pending"


# -----------------------------------------------------------------------
# 9. Enum serialization
# -----------------------------------------------------------------------


class TestIDLAndEnums:
    """Test real IDL loading and enum type access via anchorpy Program."""

    def _make_client(self):
        """Create a real AgentArenaClient with the converted IDL."""
        from solders.keypair import Keypair
        from solders.pubkey import Pubkey
        from solana.rpc.async_api import AsyncClient
        from anchorpy import Provider, Wallet
        from src.chain.program_client import AgentArenaClient

        kp = Keypair()
        client = AsyncClient("https://api.devnet.solana.com")
        wallet = Wallet(kp)
        provider = Provider(client, wallet)
        return AgentArenaClient(provider, Pubkey.new_unique())

    def test_idl_loads_successfully(self):
        """The IDL compatibility layer produces a working Program."""
        client = self._make_client()
        assert client.program is not None
        assert len(client.program.idl.instructions) == 8

    def test_challenge_type_enum_accessible(self):
        client = self._make_client()
        ct = client.challenge_type_swap_execution()
        assert str(ct) == "ChallengeType.SwapExecution()"

    def test_completion_status_enums_accessible(self):
        client = self._make_client()
        assert str(client.completion_complete()) == "CompletionStatus.Complete()"
        assert str(client.completion_incomplete()) == "CompletionStatus.Incomplete()"
        assert str(client.completion_invalid()) == "CompletionStatus.Invalid()"

    def test_all_type_keys_present(self):
        client = self._make_client()
        type_keys = list(client.program.type.keys())
        assert "ChallengeType" in type_keys
        assert "CompletionStatus" in type_keys
        assert "RunStatus" in type_keys
        assert "ChallengeStatus" in type_keys

    def test_idl_compat_convert_type(self):
        """Verify the type converter handles all cases."""
        from src.chain.idl_compat import convert_type

        assert convert_type("pubkey") == "publicKey"
        assert convert_type("u64") == "u64"
        assert convert_type({"defined": {"name": "Foo"}}) == {"defined": "Foo"}
        assert convert_type({"option": "pubkey"}) == {"option": "publicKey"}
        assert convert_type({"array": ["u8", 32]}) == {"array": ["u8", 32]}


# -----------------------------------------------------------------------
# 10. Auth dependencies
# -----------------------------------------------------------------------


class TestAuth:
    def test_privy_user_dataclass(self):
        from src.auth import PrivyUser

        user = PrivyUser(privy_user_id="user-123", wallet_address="abc")
        assert user.privy_user_id == "user-123"

    def test_privy_user_optional_wallet(self):
        from src.auth import PrivyUser

        user = PrivyUser(privy_user_id="user-456")
        assert user.wallet_address is None


# -----------------------------------------------------------------------
# 10. DB engine module
# -----------------------------------------------------------------------


class TestDBEngine:
    def test_engine_exists(self):
        from src.db.engine import engine

        assert engine is not None

    def test_session_factory_exists(self):
        from src.db.engine import async_session_factory

        assert async_session_factory is not None

    def test_get_db_is_async_generator(self):
        import inspect
        from src.db.engine import get_db

        assert inspect.isasyncgenfunction(get_db)


# -----------------------------------------------------------------------
# 11. Module imports
# -----------------------------------------------------------------------


class TestModuleImports:
    def test_import_main(self):
        from src.main import app

        assert app is not None

    def test_import_auth(self):
        from src.auth import PrivyUser, get_current_user, require_admin

        assert all([PrivyUser, get_current_user, require_admin])

    def test_import_solana_service(self):
        from src.services.solana_service import SolanaService

        assert SolanaService is not None

    def test_import_program_client(self):
        from src.chain.program_client import AgentArenaClient

        assert AgentArenaClient is not None

    def test_import_strategy_service(self):
        from src.services.strategy_service import StrategyService

        assert StrategyService is not None

    def test_import_challenge_service(self):
        from src.services.challenge_service import ChallengeService

        assert ChallengeService is not None

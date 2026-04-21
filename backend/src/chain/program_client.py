"""AgentArenaClient — live anchorpy client for the Agent Arena program.

Uses idl_compat to convert the Anchor 0.32.1 IDL to legacy format,
then loads a real anchorpy Program instance with typed enum access.
Enum arguments use program.type["EnumName"].Variant() — not raw dicts.
"""

from __future__ import annotations

from pathlib import Path

from anchorpy import Context, Idl, Program, Provider
from solders.instruction import AccountMeta  # type: ignore[import-untyped]
from solders.keypair import Keypair  # type: ignore[import-untyped]
from solders.pubkey import Pubkey  # type: ignore[import-untyped]
from solders.system_program import ID as SYS_PROGRAM_ID  # type: ignore[import-untyped]

from src.chain.idl_compat import load_and_convert
from src.config import settings

# PDA seeds — must match constants.rs exactly
CONFIG_SEED = b"config"
STRATEGY_SEED = b"strategy"
CHALLENGE_SEED = b"challenge"
RUN_SEED = b"run"
AGENT_RANK_SEED = b"agent_rank"

IDL_PATH = Path(__file__).parent / "idl" / "agent_arena.json"


class AgentArenaClient:
    """Live anchorpy client for the Agent Arena Anchor program."""

    def __init__(self, provider: Provider, program_id: Pubkey | None = None):
        self.provider = provider
        self.program_id = program_id or Pubkey.from_string(settings.PROGRAM_ID)

        # Load IDL via compatibility layer
        legacy_json = load_and_convert(IDL_PATH)
        idl = Idl.from_json(legacy_json)
        self.program = Program(idl, self.program_id, self.provider)

    # -------------------------------------------------------------------
    # Enum accessors — use program.type for real anchorpy enum values
    # -------------------------------------------------------------------

    def challenge_type_swap_execution(self):
        return self.program.type["ChallengeType"].SwapExecution()

    def completion_complete(self):
        return self.program.type["CompletionStatus"].Complete()

    def completion_incomplete(self):
        return self.program.type["CompletionStatus"].Incomplete()

    def completion_invalid(self):
        return self.program.type["CompletionStatus"].Invalid()

    # -------------------------------------------------------------------
    # PDA derivation helpers
    # -------------------------------------------------------------------

    def derive_config_pda(self) -> tuple[Pubkey, int]:
        return Pubkey.find_program_address([CONFIG_SEED], self.program_id)

    def derive_strategy_pda(self, owner: Pubkey, agent_id: int) -> tuple[Pubkey, int]:
        return Pubkey.find_program_address(
            [STRATEGY_SEED, bytes(owner), agent_id.to_bytes(8, "little")],
            self.program_id,
        )

    def derive_challenge_pda(self, challenge_id: int) -> tuple[Pubkey, int]:
        return Pubkey.find_program_address(
            [CHALLENGE_SEED, challenge_id.to_bytes(8, "little")],
            self.program_id,
        )

    def derive_run_pda(self, challenge_id: int, agent_id: int) -> tuple[Pubkey, int]:
        return Pubkey.find_program_address(
            [RUN_SEED, challenge_id.to_bytes(8, "little"), agent_id.to_bytes(8, "little")],
            self.program_id,
        )

    def derive_agent_rank_pda(self, agent_id: int) -> tuple[Pubkey, int]:
        return Pubkey.find_program_address(
            [AGENT_RANK_SEED, agent_id.to_bytes(8, "little")],
            self.program_id,
        )

    # -------------------------------------------------------------------
    # Instructions — real anchorpy RPC calls
    # -------------------------------------------------------------------

    async def initialize(self) -> str:
        config_pda, _ = self.derive_config_pda()
        tx = await self.program.rpc["initialize"](
            ctx=Context(accounts={
                "config": config_pda,
                "admin": self.provider.wallet.public_key,
                "system_program": SYS_PROGRAM_ID,
            }),
        )
        return str(tx)

    async def register_strategy(
        self, agent_id: int, agent_name: str, submission_hash: bytes,
        metadata_ref: str, owner_keypair: Keypair,
    ) -> tuple[str, Pubkey]:
        """Owner-signed — NOT authority-signed."""
        strategy_pda, _ = self.derive_strategy_pda(owner_keypair.pubkey(), agent_id)
        tx = await self.program.rpc["register_strategy"](
            agent_id, agent_name, list(submission_hash), metadata_ref,
            ctx=Context(
                accounts={
                    "strategy_account": strategy_pda,
                    "owner": owner_keypair.pubkey(),
                    "system_program": SYS_PROGRAM_ID,
                },
                signers=[owner_keypair],
            ),
        )
        return str(tx), strategy_pda

    async def create_challenge(
        self, challenge_id: int, challenge_version: int, starting_usdc: int,
        usdc_mint: Pubkey, max_slippage_bps: int, iteration_budget: int,
        time_budget_secs: int, num_contestants: int,
    ) -> tuple[str, Pubkey]:
        challenge_pda, _ = self.derive_challenge_pda(challenge_id)
        config_pda, _ = self.derive_config_pda()
        tx = await self.program.rpc["create_challenge"](
            challenge_id,
            self.challenge_type_swap_execution(),
            challenge_version,
            starting_usdc,
            usdc_mint,
            max_slippage_bps,
            iteration_budget,
            time_budget_secs,
            num_contestants,
            ctx=Context(accounts={
                "challenge_account": challenge_pda,
                "config": config_pda,
                "authority": self.provider.wallet.public_key,
                "system_program": SYS_PROGRAM_ID,
            }),
        )
        return str(tx), challenge_pda

    async def create_run(
        self, challenge_id: int, agent_id: int, benchmark_wallet: Pubkey,
        strategy_pda: Pubkey,
    ) -> tuple[str, Pubkey]:
        run_pda, _ = self.derive_run_pda(challenge_id, agent_id)
        challenge_pda, _ = self.derive_challenge_pda(challenge_id)
        tx = await self.program.rpc["create_run"](
            challenge_id, agent_id, benchmark_wallet,
            ctx=Context(accounts={
                "run_account": run_pda,
                "challenge_account": challenge_pda,
                "strategy_account": strategy_pda,
                "authority": self.provider.wallet.public_key,
                "system_program": SYS_PROGRAM_ID,
            }),
        )
        return str(tx), run_pda

    async def start_challenge(self, challenge_id: int) -> str:
        challenge_pda, _ = self.derive_challenge_pda(challenge_id)
        tx = await self.program.rpc["start_challenge"](
            ctx=Context(accounts={
                "challenge_account": challenge_pda,
                "authority": self.provider.wallet.public_key,
            }),
        )
        return str(tx)

    async def finalize_run(
        self, challenge_id: int, agent_id: int, ending_usdc: int,
        run_log_hash: bytes, completion_status_variant: str,
        iterations_used: int,
    ) -> str:
        """completion_status_variant: 'Complete', 'Incomplete', or 'Invalid'."""
        run_pda, _ = self.derive_run_pda(challenge_id, agent_id)
        challenge_pda, _ = self.derive_challenge_pda(challenge_id)
        cs = getattr(self.program.type["CompletionStatus"], completion_status_variant)()
        tx = await self.program.rpc["finalize_run"](
            ending_usdc, list(run_log_hash), cs, iterations_used,
            ctx=Context(accounts={
                "run_account": run_pda,
                "challenge_account": challenge_pda,
                "authority": self.provider.wallet.public_key,
            }),
        )
        return str(tx)

    async def settle_challenge(self, challenge_id: int, run_pdas: list[Pubkey]) -> str:
        challenge_pda, _ = self.derive_challenge_pda(challenge_id)
        # anchorpy requires AccountMeta objects on remaining_accounts, not dicts.
        remaining = [
            AccountMeta(pubkey=p, is_signer=False, is_writable=False)
            for p in run_pdas
        ]
        tx = await self.program.rpc["settle_challenge"](
            ctx=Context(
                accounts={
                    "challenge_account": challenge_pda,
                    "authority": self.provider.wallet.public_key,
                },
                remaining_accounts=remaining,
            ),
        )
        return str(tx)

    async def update_agent_rank(
        self, agent_id: int, strategy_pda: Pubkey, score: int,
        rank_version: int, wins: int, losses: int, total_challenges: int,
        avg_execution_quality: int, consistency: int, invalid_runs: int,
    ) -> str:
        rank_pda, _ = self.derive_agent_rank_pda(agent_id)
        config_pda, _ = self.derive_config_pda()
        tx = await self.program.rpc["update_agent_rank"](
            agent_id, score, rank_version, wins, losses, total_challenges,
            avg_execution_quality, consistency, invalid_runs,
            ctx=Context(accounts={
                "agent_rank_account": rank_pda,
                "strategy_account": strategy_pda,
                "config": config_pda,
                "authority": self.provider.wallet.public_key,
                "system_program": SYS_PROGRAM_ID,
            }),
        )
        return str(tx)

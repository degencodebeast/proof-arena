"""ChallengeService — challenge lifecycle management.

Benchmark truth boundary: chain-backed operations require a program client.
If no program client, operations that need chain state raise explicitly.
DB-only mode is allowed ONLY for queries, not for state transitions.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.chain.program_client import AgentArenaClient
from src.config import settings
from src.db.models import Agent, AgentInstance, AgentTemplate, Challenge, Run

logger = logging.getLogger(__name__)


class OnchainError(Exception):
    """Raised when an on-chain operation fails."""

    def __init__(self, operation: str, detail: str):
        self.operation = operation
        self.detail = detail
        super().__init__(f"On-chain {operation} failed: {detail}")


class InvalidInstanceStateError(Exception):
    """Raised when a hosted instance is not eligible for benchmark-run creation.

    Covers three cases (see Task 15 edge-case spec §4):
      - instance does not exist
      - ``instance.status != 'live'``
      - ``instance.superseded_by_instance_id is not None``

    This error is local to challenge/run creation. It deliberately does
    NOT overload the Task 2 saga taxonomy — saga failure reasons
    (``provisioning_failed`` etc.) describe deploy-saga state, not
    benchmark-eligibility state.
    """


class ChallengeService:
    """Manages challenge lifecycle and run creation.

    State transitions (create, start) require a program client.
    Queries work without one.
    """

    def __init__(
        self,
        db: AsyncSession,
        program_client: AgentArenaClient | None = None,
    ):
        self.db = db
        self.program = program_client

    def _require_program(self, operation: str):
        """Raise if program client is missing for chain-backed operations."""
        if self.program is None:
            raise OnchainError(
                operation,
                "No program client configured. Chain-backed state "
                "transitions require a connected AgentArenaClient.",
            )

    async def create_challenge(
        self,
        challenge_type: str = "swap_execution",
        starting_usdc: int = 100_000_000,
        swap_intents: list[str] | None = None,
        allowed_routes: list[list[str]] | None = None,
        max_slippage_bps: int = 100,
        iteration_budget: int = 20,
        time_budget_secs: int = 300,
        llm_provider: str = "anthropic",
        llm_model: str = "claude-sonnet-4-20250514",
        contestant_agent_ids: list[int] | None = None,
    ) -> Challenge:
        """Create a new challenge. Requires program client."""
        self._require_program("create_challenge")

        config = {
            "starting_usdc": starting_usdc,
            "swap_intents": swap_intents or [],
            "allowed_routes": allowed_routes or [],
            "max_slippage_bps": max_slippage_bps,
            "iteration_budget": iteration_budget,
            "time_budget_secs": time_budget_secs,
        }
        contestant_ids = contestant_agent_ids or []
        num_contestants = len(contestant_ids)

        # Postgres record first
        challenge = Challenge(
            challenge_type=challenge_type,
            challenge_version=settings.CHALLENGE_VERSION,
            llm_provider=llm_provider,
            llm_model=llm_model,
            config_json=json.dumps(config, sort_keys=True),
            status="pending",
            num_contestants=num_contestants,
            num_finalized=0,
        )
        self.db.add(challenge)
        await self.db.flush()

        # On-chain
        try:
            from solders.pubkey import Pubkey  # type: ignore[import-untyped]

            tx_sig, challenge_pda = await self.program.create_challenge(
                challenge_id=challenge.challenge_id,
                challenge_version=1,
                starting_usdc=starting_usdc,
                usdc_mint=Pubkey.default(),
                max_slippage_bps=max_slippage_bps,
                iteration_budget=iteration_budget,
                time_budget_secs=time_budget_secs,
                num_contestants=num_contestants,
            )
            challenge.onchain_address = str(challenge_pda)
        except Exception as e:
            challenge.status = "onchain_failed"
            await self.db.commit()
            raise OnchainError("create_challenge", str(e)) from e

        await self.db.commit()

        # Create runs for contestants
        for agent_id in contestant_ids:
            await self.create_run(challenge.challenge_id, agent_id)

        return challenge

    async def create_run(
        self,
        challenge_id: int,
        agent_id: int,
        benchmark_wallet_address: str | None = None,
        benchmark_wallet_ref: str | None = None,
    ) -> Run:
        """Create a run for an agent in a challenge.

        If the agent has no on-chain address (pending_onchain), the run
        is created with status='pending_onchain' — it cannot be started
        until the agent's on-chain registration completes.
        """
        challenge = await self.get_by_id(challenge_id)
        if challenge is None:
            raise ValueError(f"Challenge {challenge_id} not found")

        agent = await self.db.get(Agent, agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")

        # Determine initial status based on agent's on-chain state
        has_onchain_agent = agent.onchain_address is not None
        initial_status = "pending" if has_onchain_agent else "pending_onchain"

        run = Run(
            challenge_id=challenge_id,
            agent_id=agent_id,
            provider_type="local",
            benchmark_wallet_address=benchmark_wallet_address,
            benchmark_wallet_ref=benchmark_wallet_ref,
            status=initial_status,
            starting_value=int(
                json.loads(challenge.config_json).get("starting_usdc", 0)
            ),
            app_version=settings.APP_VERSION,
            challenge_type=challenge.challenge_type,
            challenge_version=settings.CHALLENGE_VERSION,
            action_schema_version=settings.ACTION_SCHEMA_VERSION,
            evidence_schema_version=settings.EVIDENCE_SCHEMA_VERSION,
        )
        self.db.add(run)
        await self.db.flush()

        # On-chain registration only if agent has on-chain address
        if has_onchain_agent and self.program is not None:
            try:
                from solders.pubkey import Pubkey  # type: ignore[import-untyped]

                strategy_pda = Pubkey.from_string(agent.onchain_address)
                wallet_pk = (
                    Pubkey.from_string(benchmark_wallet_address)
                    if benchmark_wallet_address
                    else Pubkey.default()
                )
                tx_sig, run_pda = await self.program.create_run(
                    challenge_id=challenge_id,
                    agent_id=agent_id,
                    benchmark_wallet=wallet_pk,
                    strategy_pda=strategy_pda,
                )
                run.onchain_address = str(run_pda)
            except Exception as e:
                logger.error(
                    "On-chain create_run failed for challenge=%d agent=%d: %s",
                    challenge_id, agent_id, str(e),
                )
                run.status = "onchain_failed"

        await self.db.commit()
        return run

    async def start_challenge(self, challenge_id: int) -> Challenge:
        """Start a pending challenge. Requires program client.

        On-chain must succeed before Postgres transitions.
        """
        self._require_program("start_challenge")

        challenge = await self.get_by_id(challenge_id)
        if challenge is None:
            raise ValueError(f"Challenge {challenge_id} not found")
        if challenge.status != "pending":
            raise ValueError(
                f"Challenge {challenge_id} is {challenge.status}, not pending"
            )

        # On-chain first
        try:
            await self.program.start_challenge(challenge_id)
        except Exception as e:
            raise OnchainError("start_challenge", str(e)) from e

        # Only transition Postgres after on-chain success
        challenge.status = "active"
        challenge.started_at = datetime.now(timezone.utc)
        await self.db.commit()
        return challenge

    # -------------------------------------------------------------------
    # Queries — no program client required
    # -------------------------------------------------------------------

    async def get_by_id(self, challenge_id: int) -> Challenge | None:
        result = await self.db.execute(
            select(Challenge).where(Challenge.challenge_id == challenge_id)
        )
        return result.scalar_one_or_none()

    async def get_active(self) -> list[Challenge]:
        result = await self.db.execute(
            select(Challenge)
            .where(Challenge.status == "active")
            .order_by(Challenge.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_all(self, status: str | None = None) -> list[Challenge]:
        query = select(Challenge).order_by(Challenge.created_at.desc())
        if status:
            query = query.where(Challenge.status == status)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_runs(self, challenge_id: int) -> list[Run]:
        result = await self.db.execute(
            select(Run)
            .where(Run.challenge_id == challenge_id)
            .order_by(Run.agent_id)
        )
        return list(result.scalars().all())

    # -------------------------------------------------------------------
    # V2 Task 15 — hosted-instance benchmark run creation
    # -------------------------------------------------------------------

    async def create_run_for_instance(
        self, instance_id: int, challenge_config: dict
    ) -> Run:
        """Create a benchmark run for a live hosted ``AgentInstance``.

        V2 hosted-instance path. Contract (see ``.taskmaster/docs/task15-edge-case-spec.md``):

        - ``challenge_config`` must contain ``challenge_id``.
        - Instance must exist, be ``live``, and not be superseded.
        - Creates (or reuses) an ``Agent`` row with
          ``subject_type="customized_instance"`` for run attachment.
        - Emits a ``Run`` with ``provider_type="hosted_instance"``,
          wallet refs inherited from the instance, and
          ``onchain_address=None`` — V2 hosted runs do NOT create an
          on-chain RunAccount (V2 plan §3: zero new Anchor work).

        Creates the ``Run`` row only. The returned run is ``status="pending"``.
        Execution wiring — constructing ``HostedInstanceProvider(runtime,
        handle)`` from ``instance.runtime_handle_json`` and invoking
        ``runner_service.execute_run(run, challenge, provider)`` — is a
        downstream orchestration concern owned by the caller: the flagship
        cron (Task 19 / plan D-2) for scheduled runs and the instance
        dashboard "Benchmark-now" action (Task 17 / plan E-4) for
        user-triggered runs. ``runner_service.execute_run`` currently
        takes a caller-supplied ``provider`` argument — there is no
        provider-type-based dispatcher in V2, and Task 15 does not
        introduce one.

        Does NOT attach reputation to the canonical template.
        """
        challenge_id = challenge_config.get("challenge_id")
        if challenge_id is None:
            raise ValueError(
                "challenge_config missing 'challenge_id'"
            )

        instance = await self._get_instance(instance_id)

        challenge = await self.get_by_id(challenge_id)
        if challenge is None:
            raise ValueError(f"Challenge {challenge_id} not found")

        agent = await self._get_or_create_instance_agent(instance)

        starting_value = int(
            json.loads(challenge.config_json).get("starting_usdc", 0)
        )

        run = Run(
            challenge_id=challenge.challenge_id,
            agent_id=agent.agent_id,
            provider_type="hosted_instance",
            benchmark_wallet_address=instance.wallet_address,
            benchmark_wallet_ref=instance.hosted_wallet_ref,
            status="pending",
            starting_value=starting_value,
            app_version=settings.APP_VERSION,
            challenge_type=challenge.challenge_type,
            challenge_version=challenge.challenge_version,
            action_schema_version=settings.ACTION_SCHEMA_VERSION,
            evidence_schema_version=settings.EVIDENCE_SCHEMA_VERSION,
        )
        self.db.add(run)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ValueError(
                f"Run for (challenge_id={challenge_id}, instance_id={instance_id}) "
                f"already exists"
            ) from exc
        return run

    async def _get_instance(self, instance_id: int) -> AgentInstance:
        """Resolve + validate an instance for benchmark-run creation.

        Raises ``InvalidInstanceStateError`` on: missing, non-``live``
        status, or superseded (``superseded_by_instance_id`` set).
        """
        instance = await self.db.get(AgentInstance, instance_id)
        if instance is None:
            raise InvalidInstanceStateError(
                f"Instance {instance_id} not found"
            )
        if instance.status != "live":
            raise InvalidInstanceStateError(
                f"Cannot benchmark instance {instance_id} in status "
                f"{instance.status!r}; only 'live' instances are eligible"
            )
        if instance.superseded_by_instance_id is not None:
            raise InvalidInstanceStateError(
                f"Instance {instance_id} has been superseded by "
                f"{instance.superseded_by_instance_id}"
            )
        return instance

    async def _get_or_create_instance_agent(
        self, instance: AgentInstance
    ) -> Agent:
        """Resolve the ``Agent`` row for a hosted instance (or create it).

        Uses ``privy_user_id = 'instance:{instance_id}'`` as a stable
        synthetic key so a second call for the same instance reuses the
        existing row (idempotent). The created row carries
        ``subject_type='customized_instance'`` (A-4 CHECK) and
        ``provider_type='hosted_instance'`` so downstream readers can
        distinguish it from canonical-template agents.

        Concurrency: a partial unique index
        (``uq_agents_privy_user_id_customized_instance``, Alembic
        ``a1b2c3d4e5f6``) enforces the synthetic key uniqueness at the
        DB level. The insert is wrapped in a savepoint so a lost race
        (``IntegrityError``) does NOT poison the outer transaction —
        we roll back the savepoint, reload the committed row, and
        return it.
        """
        synthetic_key = f"instance:{instance.instance_id}"
        result = await self.db.execute(
            select(Agent).where(
                Agent.privy_user_id == synthetic_key,
                Agent.subject_type == "customized_instance",
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing

        # Pull the template's system_prompt for lineage; templates are
        # required (FK NOT NULL on agent_instances.template_id) so this
        # lookup always succeeds.
        template = await self.db.get(AgentTemplate, instance.template_id)
        system_prompt = template.system_prompt if template is not None else ""
        template_key = template.template_key if template is not None else "unknown"

        config_json = instance.effective_config_json or "{}"
        submission_hash = hashlib.sha256(
            f"instance:{instance.instance_id}:{config_json}".encode("utf-8")
        ).hexdigest()

        # owner_wallet must be NOT NULL; the instance always has a wallet
        # by the time it reaches 'live' (Task 13 saga step 3 creates it
        # before the row is persisted).
        owner_wallet = instance.wallet_address or ""

        agent = Agent(
            privy_user_id=synthetic_key,
            owner_wallet=owner_wallet,
            display_name=f"instance:{template_key}:{instance.instance_id}"[:64],
            submission_type="hosted_instance",
            submission_hash=submission_hash,
            system_prompt=system_prompt,
            config_json=config_json,
            metadata_ref=f"agent_instances/{instance.instance_id}",
            provider_type="hosted_instance",
            provider_config_json=instance.runtime_handle_json,
            subject_type="customized_instance",
        )
        try:
            async with self.db.begin_nested():
                self.db.add(agent)
                await self.db.flush()
        except IntegrityError:
            # A concurrent caller won the race against the partial unique
            # index. Savepoint already rolled back; reload the committed
            # winner and return it.
            result = await self.db.execute(
                select(Agent).where(
                    Agent.privy_user_id == synthetic_key,
                    Agent.subject_type == "customized_instance",
                )
            )
            agent = result.scalar_one()
        return agent

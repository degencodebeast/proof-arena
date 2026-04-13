"""StrategyService — strategy registration with dual-write pattern.

Ownership model: The backend does NOT claim to be the strategy owner on-chain.
On-chain registration requires the actual owner's keypair (owner-signed instruction).
In Task 4, on-chain registration is DEFERRED until the user provides a signature
(via Privy embedded wallet in Task 11). Postgres records this explicitly.

Flow: normalize → hash → Postgres (status=pending_onchain) → return.
On-chain registration happens later when the owner can sign.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.chain.program_client import AgentArenaClient
from src.db.models import Agent


class OnchainRegistrationError(Exception):
    """Raised when on-chain strategy registration fails."""

    def __init__(self, message: str, tx_error: str | None = None):
        super().__init__(message)
        self.tx_error = tx_error


class StrategyService:
    """Manages strategy registration and queries."""

    def __init__(
        self, db: AsyncSession, program_client: AgentArenaClient | None = None
    ):
        self.db = db
        self.program = program_client

    @staticmethod
    def compute_submission_hash(system_prompt: str, config_json: dict) -> str:
        """Compute deterministic SHA-256 of normalized submission.

        Normalization: strip whitespace from prompt, sort config keys,
        concatenate as canonical JSON.
        """
        normalized_config = json.dumps(
            config_json, sort_keys=True, separators=(",", ":")
        )
        normalized = f"{system_prompt.strip()}\n{normalized_config}"
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    async def register_strategy(
        self,
        privy_user_id: str,
        owner_wallet: str,
        display_name: str,
        system_prompt: str,
        config_json: dict | None = None,
        metadata_ref: str | None = None,
        twitter_handle: str | None = None,
    ) -> Agent:
        """Register a new strategy in Postgres.

        On-chain registration is DEFERRED. The on-chain register_strategy
        instruction requires the owner's keypair as signer. In V1, this
        happens when the user's Privy embedded wallet signs the transaction
        (wired in Task 11).

        The Postgres record is created with status='pending_onchain' to
        indicate the on-chain step has not completed.
        """
        config = config_json or {}
        submission_hash = self.compute_submission_hash(system_prompt, config)

        agent = Agent(
            privy_user_id=privy_user_id,
            owner_wallet=owner_wallet,
            display_name=display_name,
            submission_type="local",
            submission_hash=submission_hash,
            system_prompt=system_prompt,
            config_json=json.dumps(config, sort_keys=True),
            metadata_ref=metadata_ref or "",
            provider_type="local",
            twitter_handle=twitter_handle,
            # On-chain registration deferred — status reflects this
            status="pending_onchain",
            moderation_status="active",
            onchain_address=None,
        )
        self.db.add(agent)
        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def complete_onchain_registration(
        self,
        agent_id: int,
        onchain_address: str,
        tx_signature: str,
    ) -> Agent:
        """Mark on-chain registration as complete.

        Called after the owner signs and the on-chain tx confirms.
        Transitions status from pending_onchain to active.
        """
        agent = await self.get_by_id(agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")
        if agent.status not in ("pending_onchain", "onchain_failed"):
            raise ValueError(
                f"Agent {agent_id} status is {agent.status}, "
                "expected pending_onchain or onchain_failed"
            )

        agent.onchain_address = onchain_address
        agent.status = "active"
        await self.db.commit()
        return agent

    async def mark_onchain_failed(
        self, agent_id: int, error_detail: str
    ) -> Agent:
        """Mark on-chain registration as failed with reason.

        Keeps the Postgres record for debugging/retry. Does not delete.
        """
        agent = await self.get_by_id(agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")

        agent.status = "onchain_failed"
        # Store error in metadata_ref for debugging (not ideal, but minimal)
        agent.metadata_ref = f"onchain_error:{error_detail[:200]}"
        await self.db.commit()
        return agent

    async def get_by_id(self, agent_id: int) -> Agent | None:
        result = await self.db.execute(
            select(Agent).where(Agent.agent_id == agent_id)
        )
        return result.scalar_one_or_none()

    async def get_by_owner(self, privy_user_id: str) -> list[Agent]:
        result = await self.db.execute(
            select(Agent)
            .where(Agent.privy_user_id == privy_user_id)
            .order_by(Agent.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_active_count(self, privy_user_id: str) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(Agent)
            .where(
                Agent.privy_user_id == privy_user_id,
                Agent.status == "active",
            )
        )
        return result.scalar_one()

    def verify_submission_hash(
        self, agent: Agent, system_prompt: str, config_json: dict
    ) -> bool:
        recomputed = self.compute_submission_hash(system_prompt, config_json)
        return agent.submission_hash == recomputed

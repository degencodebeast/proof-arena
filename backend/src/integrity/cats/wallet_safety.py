"""Wallet Safety Cat — deterministic compute over Run + RunEvent + AgentInstance.

Spec: docs/superpowers/specs/2026-04-29-wallet-safety-cat-proof-arena-spec.md
Trust path: deterministic only. NO LLM SDK imports anywhere in this module.
"""
from __future__ import annotations
import re
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models import Agent, AgentInstance, Run
from src.integrity.cats.schemas import WalletSafetyCatResponse


_METADATA_RE = re.compile(r"^agent_instances/(?P<id>\d+)$")
_PRIVY_RE = re.compile(r"^instance:(?P<id>\d+)$")


# Domain exceptions — router maps each to the spec'd HTTP code/body.
class WalletSafetyCatError(Exception):
    """Base for Cat domain exceptions."""


class RunNotFoundError(WalletSafetyCatError):
    """run_id does not exist."""


class RunNotFinalError(WalletSafetyCatError):
    def __init__(self, lifecycle_status: str):
        self.lifecycle_status = lifecycle_status


class UnsupportedProviderTypeError(WalletSafetyCatError):
    def __init__(self, provider_type: str):
        self.provider_type = provider_type


class InstanceUnresolvableError(WalletSafetyCatError):
    """Synthetic-Agent bridge could not resolve to a concrete AgentInstance."""


class UnsupportedTrustLabelError(WalletSafetyCatError):
    def __init__(self, trust_label: str):
        self.trust_label = trust_label


async def _resolve_instance(db: AsyncSession, agent_id: int) -> tuple[Agent, AgentInstance]:
    """Resolve Run → Agent → AgentInstance via the V2 synthetic-Agent bridge.

    Lookup order: Agent.metadata_ref → Agent.privy_user_id fallback.
    All bridge-failure modes (malformed metadata, malformed privy_user_id,
    missing AgentInstance row) collapse to InstanceUnresolvableError.
    """
    agent = (await db.execute(select(Agent).where(Agent.agent_id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise InstanceUnresolvableError("missing_agent")
    instance_id: int | None = None
    if agent.metadata_ref:
        m = _METADATA_RE.match(agent.metadata_ref)
        if m:
            instance_id = int(m.group("id"))
    if instance_id is None and agent.privy_user_id:
        m = _PRIVY_RE.match(agent.privy_user_id)
        if m:
            instance_id = int(m.group("id"))
    if instance_id is None:
        raise InstanceUnresolvableError("bridge_unparseable")
    instance = await db.get(AgentInstance, instance_id)
    if instance is None:
        raise InstanceUnresolvableError("missing_agent_instance")
    return agent, instance


async def compute_wallet_safety_cat(db: AsyncSession, run_id: int) -> WalletSafetyCatResponse:
    """Deterministic Cat compute. Raises domain exceptions; never returns HTTP-shaped errors."""
    run = (await db.execute(select(Run).where(Run.run_id == run_id))).scalar_one_or_none()
    if run is None:
        raise RunNotFoundError(run_id)
    if run.completion_status is None:
        raise RunNotFinalError(lifecycle_status=run.status)
    if run.provider_type != "hosted_instance":
        raise UnsupportedProviderTypeError(run.provider_type)
    agent, instance = await _resolve_instance(db, run.agent_id)
    # Subsequent tasks (6+) add trust_label / verdict logic.
    raise NotImplementedError

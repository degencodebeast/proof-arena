"""Wallet Safety Cat — deterministic compute over Run + RunEvent + AgentInstance.

Spec: docs/superpowers/specs/2026-04-29-wallet-safety-cat-proof-arena-spec.md
Trust path: deterministic only. NO LLM SDK imports anywhere in this module.
"""
from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models import Run
from src.integrity.cats.schemas import WalletSafetyCatResponse


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


async def compute_wallet_safety_cat(db: AsyncSession, run_id: int) -> WalletSafetyCatResponse:
    """Deterministic Cat compute. Raises domain exceptions; never returns HTTP-shaped errors."""
    run = (await db.execute(select(Run).where(Run.run_id == run_id))).scalar_one_or_none()
    if run is None:
        raise RunNotFoundError(run_id)
    if run.completion_status is None:
        raise RunNotFinalError(lifecycle_status=run.status)
    # Subsequent tasks (4+) add provider / bridge / verdict logic.
    raise NotImplementedError

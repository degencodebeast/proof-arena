"""Wallet Safety Cat — deterministic compute over Run + RunEvent + AgentInstance.

Spec: docs/superpowers/specs/2026-04-29-wallet-safety-cat-proof-arena-spec.md
Trust path: deterministic only. NO LLM SDK imports anywhere in this module.
"""
from __future__ import annotations
import re
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models import Agent, AgentInstance, Run
from src.integrity.cats.schemas import WalletSafetyCatResponse
from src.integrity.failure_taxonomy import RunInvalidReason
from src.integrity.failure_taxonomy_copy import FAILURE_COPY_MAP


_METADATA_RE = re.compile(r"^agent_instances/(?P<id>\d+)$")
_PRIVY_RE = re.compile(r"^instance:(?P<id>\d+)$")


# Wallet-safety subset of RunInvalidReason (spec §8 + §6 non-goal §9).
WALLET_SAFETY_REASONS: frozenset[str] = frozenset({
    "mainnet_guard_triggered",
    "wallet_policy_rejected",
    "authorization_signature_rejected",
    "hosted_wallet_unavailable",
    "invalid_action_attempts_exceeded",
})

# Locked off-scope copy text (spec §8 — byte-equal).
OFF_SCOPE_NOTE = (
    "Run failed for a non-wallet-safety reason. "
    "Wallet Safety Cat found no wallet-safety failure; "
    "overall run validity is handled by another Cat."
)

# Stable local check IDs (spec §5.1). NEVER a RunInvalidReason member.
_CHECK_IDS: tuple[str, ...] = (
    "envelope_slippage_check",
    "envelope_token_universe_check",
    "envelope_position_size_check",
    "envelope_runtime_seconds_check",
    "envelope_iterations_check",
    "mainnet_guard_check",
    "wallet_policy_check",
    "authorization_signature_check",
    "hosted_wallet_available_check",
    "invalid_action_attempts_check",
)

# Map wallet-safety RunInvalidReason members → the per-check ID that should fail.
_REASON_TO_CHECK: dict[str, str] = {
    "mainnet_guard_triggered":           "mainnet_guard_check",
    "wallet_policy_rejected":            "wallet_policy_check",
    "authorization_signature_rejected":  "authorization_signature_check",
    "hosted_wallet_unavailable":         "hosted_wallet_available_check",
    "invalid_action_attempts_exceeded":  "invalid_action_attempts_check",
}


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
    agent = await db.get(Agent, agent_id)
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


def _compose(
    *,
    run,
    agent,
    instance,
    failing_check_id: str | None,
    reason: str | None,
    critique: str,
    off_scope_invalid_reason: str | None,
) -> WalletSafetyCatResponse:
    from src.integrity.cats.schemas import (
        WalletSafetyCheck,
        WalletSafetyEvidence,
    )
    checks = [
        WalletSafetyCheck(check_id=cid, result=("fail" if cid == failing_check_id else "pass"))
        for cid in _CHECK_IDS
    ]
    return WalletSafetyCatResponse(
        run_id=run.run_id,
        instance_id=instance.instance_id,
        subject_type=agent.subject_type,
        trust_label=instance.trust_label,
        result=("fail" if reason is not None else "pass"),
        reason=reason,
        critique=critique,
        run_completion_status=run.completion_status,
        off_scope_invalid_reason=off_scope_invalid_reason,
        scope_note=(OFF_SCOPE_NOTE if off_scope_invalid_reason else None),
        evidence=WalletSafetyEvidence(
            run_log_hash=run.run_log_hash,
            primary_event_id=None,
            verifier_url=None,
        ),
        checks=checks,
    )


def _critique_for(reason_str: str) -> str:
    """Look up critique copy via dict access on FAILURE_COPY_MAP. NEVER attribute access."""
    enum_member = RunInvalidReason(reason_str)
    copy = FAILURE_COPY_MAP[enum_member]            # dict access #1
    description = copy["description"]                # dict access #2 — TypedDict, NOT attribute
    return description[:512]


async def resolve_run_and_instance(
    db: AsyncSession, run_id: int,
) -> tuple[Run, Agent, AgentInstance]:
    """Run finality + provider-type + bridge resolution + trust-label gate.

    Used by the router for conditional auth: it preloads run+agent+instance,
    decides auth based on instance.trust_label, then calls compute_wallet_safety_cat.
    Compute then re-calls this resolver internally — small redundant DB reads in
    exchange for keeping the compute module pure (no auth-aware coupling).
    """
    run = await db.get(Run, run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    if run.completion_status is None:
        raise RunNotFinalError(lifecycle_status=run.status)
    if run.provider_type != "hosted_instance":
        raise UnsupportedProviderTypeError(run.provider_type)
    agent, instance = await _resolve_instance(db, run.agent_id)
    if instance.trust_label == "external_custom_runtime":
        raise UnsupportedTrustLabelError(instance.trust_label)
    return run, agent, instance


async def compute_wallet_safety_cat(db: AsyncSession, run_id: int) -> WalletSafetyCatResponse:
    """Deterministic Cat compute. Raises domain exceptions; never returns HTTP-shaped errors."""
    run, agent, instance = await resolve_run_and_instance(db, run_id)
    if run.invalid_reason in WALLET_SAFETY_REASONS:
        return _compose(
            run=run, agent=agent, instance=instance,
            failing_check_id=_REASON_TO_CHECK[run.invalid_reason],
            reason=run.invalid_reason,
            critique=_critique_for(run.invalid_reason),
            off_scope_invalid_reason=None,
        )
    if run.invalid_reason is not None and run.invalid_reason not in WALLET_SAFETY_REASONS:
        return _compose(
            run=run, agent=agent, instance=instance,
            failing_check_id=None, reason=None, critique="",
            off_scope_invalid_reason=run.invalid_reason,
        )
    # All-pass: complete run with no invalid_reason.
    return _compose(
        run=run, agent=agent, instance=instance,
        failing_check_id=None, reason=None, critique="",
        off_scope_invalid_reason=None,
    )

"""Rebalance Policy Cat — deterministic compute over Run + AgentInstance + rebalance_evidence_v1.

Spec: docs/superpowers/specs/2026-05-03-rebalance-executor-v1-rebalance-policy-cat-v0-proof-arena-spec.md
Trust path: deterministic only. NO LLM SDK imports anywhere in this module.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import AgentInstance, AgentTemplate, Run, RunEvent, VerificationArtifact
from src.integrity.cats.schemas import (
    RebalancePolicyCatResponse,
    RebalancePolicyEvidence,
    WalletSafetyCheck,
)
from src.integrity.cats.wallet_safety import (
    InstanceUnresolvableError,
    RunNotFinalError,
    RunNotFoundError,
    UnsupportedProviderTypeError,
    UnsupportedTrustLabelError,
    resolve_run_and_instance,
)


class RebalancePolicyCatError(Exception):
    """Base for Rebalance Policy Cat domain exceptions."""


class UnsupportedTemplateError(RebalancePolicyCatError):
    def __init__(self, template_key: str):
        self.template_key = template_key


# Stable Cat-local check ids (spec §5.6 round-5). NEVER RunInvalidReason members.
_CHECK_IDS: tuple[str, ...] = (
    "target_allocation_sum_check",
    "allowed_token_universe_check",
    "price_data_present_check",
    "rebalance_threshold_check",
    "max_trade_value_check",
    "max_position_weight_check",
    "max_slippage_check",
    "dry_run_or_devnet_check",
    "post_trade_allocation_drift_check",
    "rebalance_evidence_present_check",
)

# Cat-level critique copy — never persisted; never reuses RunInvalidReason copy.
_CHECK_CRITIQUE: dict[str, str] = {
    "target_allocation_sum_check": "Target allocations do not sum to 1.0 within ±0.01.",
    "allowed_token_universe_check": "target_allocations contains a mint outside allowed_token_universe.",
    "price_data_present_check": "prices_used has a null entry for a portfolio mint.",
    "rebalance_threshold_check": "rebalance_threshold_bps out of [1,5000] OR drift/leg-presence inconsistent.",
    "max_trade_value_check": "A planned leg exceeds max_trade_value.",
    "max_position_weight_check": "A target_allocations weight exceeds max_position_weight.",
    "max_slippage_check": "max_slippage_bps out of [0,500] or a leg slippage_bps_realized != 0 in V0.",
    "dry_run_or_devnet_check": "V0 dry-run predicate failed: dry_run is False, or a leg recorded execution.",
    "post_trade_allocation_drift_check": "drift_bps_post_run != drift_bps_pre_run in V0 dry-run.",
    "rebalance_evidence_present_check": "rebalance_evidence_v1 artifact missing or content_hash mismatch.",
}


async def compute_rebalance_policy_cat(
    db: AsyncSession, run_id: int,
) -> RebalancePolicyCatResponse:
    """Deterministic Cat compute. Raises domain exceptions; never returns HTTP-shaped errors."""
    run, agent, instance = await resolve_run_and_instance(db, run_id)
    template = await db.get(AgentTemplate, instance.template_id)
    if template is None or template.template_key != "rebalance_executor_v1":
        raise UnsupportedTemplateError(
            template.template_key if template else "unknown"
        )

    # Read evidence artifact internally (private column read).
    artifact = (
        await db.execute(
            select(VerificationArtifact).where(
                VerificationArtifact.run_id == run_id,
                VerificationArtifact.artifact_type == "rebalance_evidence_v1",
            ).order_by(VerificationArtifact.artifact_id.asc()).limit(1)
        )
    ).scalar_one_or_none()

    check_results = await _run_checks(db, run, instance, template, artifact)
    return _compose(
        run=run, agent=agent, instance=instance,
        artifact=artifact, check_results=check_results,
    )


async def _run_checks(db, run, instance, template, artifact) -> dict[str, bool]:
    results: dict[str, bool] = {cid: True for cid in _CHECK_IDS}
    if artifact is None:
        results["rebalance_evidence_present_check"] = False
        # Without evidence, downstream checks default to fail (no data).
        for cid in _CHECK_IDS:
            if cid != "rebalance_evidence_present_check":
                results[cid] = False
        return results

    body = artifact.uri_or_ref
    expected_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if expected_hash != artifact.content_hash:
        results["rebalance_evidence_present_check"] = False
        return results
    payload = json.loads(body)
    envelope = payload.get("effective_envelope", {})

    # target_allocation_sum_check
    target = payload.get("target_allocations", {})
    total = sum(float(v) for v in target.values())
    results["target_allocation_sum_check"] = abs(total - 1.0) <= 0.01

    # allowed_token_universe_check
    universe = set(envelope.get("allowed_token_universe", []))
    results["allowed_token_universe_check"] = set(target.keys()).issubset(universe)

    # price_data_present_check
    prices = payload.get("prices_used", {})
    needed = set(target.keys()) | set(payload.get("start_portfolio", {}).keys())
    results["price_data_present_check"] = all(prices.get(m) is not None for m in needed)

    # rebalance_threshold_check
    th = envelope.get("rebalance_threshold_bps")
    drift_pre = payload.get("summary", {}).get("drift_bps_pre_run", 0)
    has_legs = bool(payload.get("legs"))
    th_in_range = isinstance(th, int) and 1 <= th <= 5000
    drift_legs_consistent = (drift_pre >= th and has_legs) or (drift_pre < th and not has_legs)
    results["rebalance_threshold_check"] = th_in_range and drift_legs_consistent

    # max_trade_value_check
    mtv = envelope.get("max_trade_value", 0)
    results["max_trade_value_check"] = all(
        leg.get("size_base_units", 0) <= mtv for leg in payload.get("legs", [])
    )

    # max_position_weight_check
    mpw = envelope.get("max_position_weight", 0.0)
    results["max_position_weight_check"] = all(
        0.0 < float(w) <= mpw for w in target.values()
    )

    # max_slippage_check
    msl = envelope.get("max_slippage_bps")
    results["max_slippage_check"] = (
        isinstance(msl, int) and 0 <= msl <= 500
        and all(leg.get("slippage_bps_realized", 0) == 0 for leg in payload.get("legs", []))
    )

    # post_trade_allocation_drift_check (V0 dry-run: post == pre)
    summary = payload.get("summary", {})
    results["post_trade_allocation_drift_check"] = (
        summary.get("drift_bps_post_run") == summary.get("drift_bps_pre_run")
    )

    # dry_run_or_devnet_check (3-clause AND predicate per spec §5.6 round-5).
    clause_dry = bool(envelope.get("dry_run", False))
    clause_no_executed_leg = all(
        leg.get("status") != "executed" for leg in payload.get("legs", [])
    )
    # No RunEvent for this run.run_id may carry a non-empty tx_signature.
    tx_sig_rows = (
        await db.execute(
            select(RunEvent).where(
                RunEvent.run_id == run.run_id,
                RunEvent.tx_signature.isnot(None),
                RunEvent.tx_signature != "",
            ).limit(1)
        )
    ).scalars().all()
    clause_no_tx_sig = not tx_sig_rows
    clause_hosted = (run.provider_type == "hosted_instance")
    results["dry_run_or_devnet_check"] = (
        clause_dry and clause_no_executed_leg and clause_no_tx_sig and clause_hosted
    )

    return results


def _compose(*, run, agent, instance, artifact, check_results: dict[str, bool]) -> RebalancePolicyCatResponse:
    failing = [cid for cid, ok in check_results.items() if not ok]
    result = "fail" if failing else "pass"
    critique = "" if not failing else _CHECK_CRITIQUE.get(failing[0], "")
    return RebalancePolicyCatResponse(
        run_id=run.run_id,
        instance_id=instance.instance_id,
        subject_type=agent.subject_type,
        trust_label=instance.trust_label,
        result=result,
        reason=None,                # NEVER a RunInvalidReason; spec §6 non-goal 6
        critique=critique[:512],
        run_completion_status=run.completion_status,
        off_scope_invalid_reason=None,
        scope_note=None,
        evidence=RebalancePolicyEvidence(
            evidence_artifact_id=artifact.artifact_id if artifact else None,
            evidence_content_hash=artifact.content_hash if artifact else None,
            run_log_hash=run.run_log_hash,
            primary_event_id=None,
            verifier_url=None,
        ),
        checks=[
            WalletSafetyCheck(
                check_id=cid,
                result=("pass" if check_results[cid] else "fail"),
            )
            for cid in _CHECK_IDS
        ],
    )

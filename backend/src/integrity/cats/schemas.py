"""Wallet Safety Cat — API response shape per spec §5.1 and §8."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class WalletSafetyCheck(BaseModel):
    check_id: str = Field(..., description="Stable local check identifier; NEVER a RunInvalidReason member.")
    result: Literal["pass", "fail"]


class WalletSafetyEvidence(BaseModel):
    run_log_hash: str | None = None
    primary_event_id: int | None = None
    verifier_url: str | None = None  # Reserved; null in V2.1.0.


class WalletSafetyCatResponse(BaseModel):
    cat: Literal["wallet_safety"] = "wallet_safety"
    cat_version: Literal["v1"] = "v1"
    run_id: int
    instance_id: int
    subject_type: str  # Lineage metadata only — Agent.subject_type. NOT used for auth.
    trust_label: str   # AgentInstance.trust_label. Auth gate.
    result: Literal["pass", "fail"]
    reason: str | None = None
    critique: str = ""
    run_completion_status: Literal["complete", "incomplete", "invalid"]
    off_scope_invalid_reason: str | None = None
    scope_note: str | None = None
    evidence: WalletSafetyEvidence
    checks: list[WalletSafetyCheck]


class RebalancePolicyEvidence(BaseModel):
    """Locked Cat evidence allowlist; uri_or_ref is NEVER a field on this surface."""
    evidence_artifact_id: int | None = None
    evidence_content_hash: str | None = None
    run_log_hash: str | None = None
    primary_event_id: int | None = None
    verifier_url: str | None = None  # Reserved; null in V0.


class RebalancePolicyCatResponse(BaseModel):
    cat: Literal["rebalance_policy"] = "rebalance_policy"
    cat_version: Literal["v1"] = "v1"
    run_id: int
    instance_id: int
    subject_type: str       # lineage metadata only
    trust_label: str        # auth gate (mirrors WalletSafetyCat)
    result: Literal["pass", "fail"]
    reason: str | None = None
    critique: str = ""
    run_completion_status: Literal["complete", "incomplete", "invalid"]
    off_scope_invalid_reason: str | None = None
    scope_note: str | None = None
    evidence: RebalancePolicyEvidence
    checks: list[WalletSafetyCheck]   # reuse same check_id/result shape

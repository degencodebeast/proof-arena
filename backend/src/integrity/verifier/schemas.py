"""Public Verifier V0 — response schemas with explicit field allowlists.

Discipline: every field is listed by hand. NO `from_attributes=True` against
ORM rows; NO inheritance from db.models.*. The builder constructs each model
field-by-field at the call site so a private ORM column can never silently
leak into the public surface.
"""
from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel

from src.integrity.cats.schemas import WalletSafetyCatResponse


class VerifierRunBlock(BaseModel):
    run_id: int
    challenge_id: int
    status: str
    completion_status: str
    invalid_reason: Optional[str] = None
    provider_type: str
    starting_value: int
    ending_value: Optional[int] = None
    iterations_used: int
    run_log_hash: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    created_at: datetime
    app_version: str
    challenge_type: str
    challenge_version: str
    action_schema_version: str
    evidence_schema_version: str


class VerifierTemplateBlock(BaseModel):
    template_key: str
    template_version: str
    template_version_at_deploy: str
    description: str
    is_deployable: bool


class VerifierLineageBlock(BaseModel):
    instance_id: int
    trust_label: str
    subject_type: str
    template: VerifierTemplateBlock


class VerifierVerificationArtifactEntry(BaseModel):
    artifact_id: int
    artifact_type: str
    content_hash: str
    created_at: datetime


class VerifierEvidenceBlock(BaseModel):
    run_log_hash: Optional[str] = None
    run_event_count: int
    last_event_sequence_no: Optional[int] = None
    last_event_type: Optional[str] = None
    verification_artifacts: list[VerifierVerificationArtifactEntry]


class VerifierCatsBlock(BaseModel):
    wallet_safety: WalletSafetyCatResponse


class VerifierRunResponse(BaseModel):
    verifier_version: Literal["v0"] = "v0"
    run: VerifierRunBlock
    lineage: VerifierLineageBlock
    evidence: VerifierEvidenceBlock
    cats: VerifierCatsBlock

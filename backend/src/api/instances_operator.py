"""Operator repair endpoints for stuck V2 hosted instances.

Closes the repair loop opened by Task 13's deploy saga. Three surfaces:

- ``GET /api/v1/instances/operator/failed`` — list instances in
  ``*_failed`` saga states (``wallet_created_runtime_failed``,
  ``runtime_live_consent_failed``, ``provisioning_failed``).
- ``POST /api/v1/instances/operator/{instance_id}/retry-consent`` —
  promote ``runtime_live_consent_failed`` → ``live`` by (re)writing the
  deploy-time consent artifact.
- ``POST /api/v1/instances/operator/{instance_id}/teardown`` —
  compensating teardown. Calls ``runtime.teardown(handle)`` when a
  handle exists (AgentOS **session** cleanup — not agent destruction —
  per the Task 12 SDK contract) and transitions the Proof Arena row to
  ``torn_down``.

All routes gate on ``require_admin`` (existing ``src.auth`` dependency).

Runtime dependency is injected via ``get_runtime()`` so tests can stub
it without touching the real AgentOS client. Production wiring reads
``settings.AGENTOS_*`` and returns an ``AgentOSRuntime`` or ``None``
when the integration isn't configured in the current environment.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import PrivyUser, require_admin
from src.config import settings
from src.db.engine import get_db
from src.db.models import AgentInstance, VerificationArtifact
from src.integrity.failure_taxonomy import SagaFailureReason
from src.integrity.saga_statuses import SagaStatus
from src.policy.engine import InstancePolicyEngine, PolicyEngineError
from src.runtime.base import InstanceHandle, InstanceRuntime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/instances/operator", tags=["operator"])


# ---------------------------------------------------------------------
# Runtime factory (injected; tests override)
# ---------------------------------------------------------------------


def get_runtime() -> Optional[InstanceRuntime]:
    """Return the concrete V2 runtime or ``None`` when unconfigured.

    Production wiring: instantiate ``AgentOSRuntime`` from settings.
    Import is local so unit tests can override this dependency without
    paying the AgentOS SDK import cost.
    """
    if not settings.AGENTOS_API_URL or not settings.AGENTOS_CANONICAL_AGENT_ID:
        return None
    from src.runtime.agentos import AgentOSRuntime  # local import

    return AgentOSRuntime(
        api_url=settings.AGENTOS_API_URL,
        auth_token=settings.AGENTOS_AUTH_TOKEN,
        canonical_agent_id=settings.AGENTOS_CANONICAL_AGENT_ID,
    )


# ---------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------


_FAILED_STATES: tuple[str, ...] = (
    SagaStatus.WALLET_CREATED_RUNTIME_FAILED.value,
    SagaStatus.RUNTIME_LIVE_CONSENT_FAILED.value,
    SagaStatus.PROVISIONING_FAILED.value,
)


class _RetryConsentBody(BaseModel):
    """4-ack deploy-time consent payload — same shape as Task 13 deploy.

    Fields are ``Optional[StrictBool]`` with default ``None``:

    - Missing key or explicit ``null``   → accepted by schema, rejected by
      ``InstancePolicyEngine.record_consent`` as 400 (must-be-True check).
    - Explicit ``false``                  → accepted by schema, rejected by
      ``record_consent`` as 400.
    - Non-boolean coercions (``"yes"``,
      ``"true"``, ``"1"``, ``1``, ``0``)  → rejected at the Pydantic schema
      layer as 422. Consent acknowledgments must be real booleans; string
      or integer short-hands would make evidence hashes ambiguous.

    ``StrictBool`` disables Pydantic's default coercion. Missing-or-False
    ack validation stays in the policy engine so the retry-consent surface
    behaves uniformly with Task 13's deploy saga.
    """

    model_config = ConfigDict(extra="forbid")

    devnet_only_acknowledged: Optional[StrictBool] = None
    platform_managed_signing_acknowledged: Optional[StrictBool] = None
    spend_caps_acknowledged: Optional[StrictBool] = None
    no_indemnity_acknowledged: Optional[StrictBool] = None


def _project_failed_row(inst: AgentInstance) -> dict[str, Any]:
    """Minimal operator-visible projection of a failed instance row."""
    return {
        "instance_id": inst.instance_id,
        "template_id": inst.template_id,
        "instance_owner_ref": inst.instance_owner_ref,
        "status": inst.status,
        "last_failure_reason": inst.last_failure_reason,
        "hosted_wallet_ref": inst.hosted_wallet_ref,
        "wallet_address": inst.wallet_address,
        "runtime_handle_json": inst.runtime_handle_json,
        "created_at": inst.created_at.isoformat() if inst.created_at else None,
    }


# ---------------------------------------------------------------------
# GET /failed
# ---------------------------------------------------------------------


@router.get("/failed")
async def list_failed_instances(
    admin: PrivyUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return instances in repair-relevant ``*_failed`` saga states."""
    result = await db.execute(
        select(AgentInstance)
        .where(AgentInstance.status.in_(_FAILED_STATES))
        .order_by(
            AgentInstance.created_at.desc(),
            AgentInstance.instance_id.desc(),
        )
    )
    return [_project_failed_row(r) for r in result.scalars().all()]


# ---------------------------------------------------------------------
# POST /{instance_id}/retry-consent
# ---------------------------------------------------------------------


@router.post("/{instance_id}/retry-consent")
async def retry_consent(
    instance_id: int,
    body: _RetryConsentBody,
    admin: PrivyUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Promote ``runtime_live_consent_failed`` instances to ``live``.

    Mirrors Task 13 step 6: ``record_consent`` → ``VerificationArtifact``
    with ``run_id=None``, ``artifact_type='deployment_consent'``,
    ``uri_or_ref=canonical_json``, ``content_hash=sha256``.
    """
    instance = await db.get(AgentInstance, instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="Instance not found")
    if instance.status != SagaStatus.RUNTIME_LIVE_CONSENT_FAILED.value:
        raise HTTPException(
            status_code=400,
            detail=(
                f"retry-consent is only valid for "
                f"status='{SagaStatus.RUNTIME_LIVE_CONSENT_FAILED.value}'; "
                f"current status is '{instance.status}'"
            ),
        )

    engine = InstancePolicyEngine()
    try:
        consent_record = engine.record_consent(body.model_dump())
    except PolicyEngineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    artifact = VerificationArtifact(
        run_id=None,
        artifact_type="deployment_consent",
        uri_or_ref=consent_record.canonical_json,
        content_hash=consent_record.content_hash,
    )
    db.add(artifact)
    await db.flush()

    instance.consent_artifact_id = artifact.artifact_id
    instance.status = SagaStatus.LIVE.value
    instance.last_failure_reason = None
    await db.commit()

    return {
        "instance_id": instance.instance_id,
        "status": instance.status,
        "last_failure_reason": instance.last_failure_reason,
        "consent_artifact_id": instance.consent_artifact_id,
    }


# ---------------------------------------------------------------------
# POST /{instance_id}/teardown
# ---------------------------------------------------------------------


def _parse_handle(raw: Optional[str]) -> Optional[InstanceHandle]:
    """Parse ``runtime_handle_json`` into an ``InstanceHandle`` or None.

    Returns None for NULL, malformed JSON, or a JSON shape that doesn't
    match the ``InstanceHandle`` dataclass. Callers treat None as
    "no valid handle" and skip the runtime call.
    """
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return InstanceHandle(**data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


@router.post("/{instance_id}/teardown")
async def teardown_instance(
    instance_id: int,
    admin: PrivyUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    runtime: Optional[InstanceRuntime] = Depends(get_runtime),
) -> dict[str, Any]:
    """Compensating teardown — session cleanup + ``status='torn_down'``.

    Idempotent: calling again on an already-``torn_down`` instance is a
    200 no-op. Runtime cleanup failures are logged and surfaced in the
    response as ``runtime_cleanup_ok=false``; the Proof Arena row still
    transitions to ``torn_down`` because domain state is authoritative
    regardless of SDK-side session-release outcome.
    """
    instance = await db.get(AgentInstance, instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="Instance not found")

    # Idempotent early return for already-torn-down rows.
    if instance.status == SagaStatus.TORN_DOWN.value:
        return {
            "instance_id": instance.instance_id,
            "status": instance.status,
            "runtime_cleanup_ok": True,
        }

    handle = _parse_handle(instance.runtime_handle_json)

    # Fail-closed when a handle is present but the runtime factory
    # returned None (AgentOS not configured in this environment).
    if handle is not None and runtime is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Runtime is not configured; cannot clean up session for an "
                "instance with an active runtime handle. Configure "
                "AGENTOS_API_URL + AGENTOS_CANONICAL_AGENT_ID or teardown "
                "via direct DB operator flow."
            ),
        )

    runtime_cleanup_ok = True
    runtime_cleanup_detail: Optional[str] = None
    if handle is not None:
        try:
            await runtime.teardown(handle)
        except Exception as exc:  # noqa: BLE001 — surfaced, not persisted
            logger.warning(
                "teardown: runtime.teardown failed for instance %s: %s",
                instance_id,
                exc,
            )
            runtime_cleanup_ok = False
            runtime_cleanup_detail = str(exc)
    elif instance.runtime_handle_json:
        # Handle column was non-null but unparseable — mark cleanup degraded.
        runtime_cleanup_ok = False
        runtime_cleanup_detail = "runtime_handle_json is not parseable"

    # Clear any stale last_failure_reason left over from a prior saga-
    # failure state (e.g. wallet_created_runtime_failed,
    # runtime_live_consent_failed). The Task 2 contract keeps
    # last_failure_reason populated only while status is in a *_failed
    # state; torn_down instances must present a clean terminal row.
    instance.status = SagaStatus.TORN_DOWN.value
    instance.last_failure_reason = None
    await db.commit()

    response: dict[str, Any] = {
        "instance_id": instance.instance_id,
        "status": instance.status,
        "runtime_cleanup_ok": runtime_cleanup_ok,
    }
    if runtime_cleanup_detail is not None:
        response["runtime_cleanup_detail"] = runtime_cleanup_detail
    return response

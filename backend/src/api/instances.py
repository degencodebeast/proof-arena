"""Task 17 — owner-gated instance profile read endpoint.

``GET /api/v1/instances/{instance_id}`` returns the requested
``AgentInstance`` row plus instance-specific benchmark history, scoped
by the Task 15 synthetic-key agent bridge
(``Agent.privy_user_id == f"instance:{id}"``) so canonical-template
aggregate reputation is never conflated with instance history.

Private fields (``instance_owner_ref``, ``hosted_wallet_ref``,
``wallet_address``, ``wallet_provider``, ``runtime_handle_json``,
``consent_artifact_id``) are excluded from the response body.

See ``.taskmaster/docs/task17-edge-case-spec.md`` for the full
edge-case map.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import PrivyUser, get_current_user
from src.config import settings
from src.db.engine import get_db
from src.db.models import Agent, AgentInstance, AgentTemplate, RankSnapshot, Run
from src.services.instance_service import InstanceDeployError, InstanceService

router = APIRouter(prefix="/instances", tags=["instances"])


# ---------------------------------------------------------------------
# Task 23 — deploy endpoint dependency factory
# ---------------------------------------------------------------------


def get_instance_service(
    db: AsyncSession = Depends(get_db),
) -> Optional[InstanceService]:
    """Return a composed InstanceService or None if the deploy stack is unconfigured.

    Mirrors Task 14's `get_runtime()` pattern. When any of the required
    env vars are empty, returns None; the deploy endpoint translates
    that to a 503. Tests override this dependency entirely via
    ``app.dependency_overrides`` to inject a stub service.

    Required env: HOSTED_WALLET_POLICY_ID, AUTHORIZATION_PUBKEY_B64,
    AGENTOS_API_URL, AGENTOS_CANONICAL_AGENT_ID, PRIVY_APP_ID,
    PRIVY_APP_SECRET, PRIVY_AUTHORIZATION_PRIVATE_KEY.
    """
    if (
        not settings.HOSTED_WALLET_POLICY_ID
        or not settings.AUTHORIZATION_PUBKEY_B64
        or not settings.AGENTOS_API_URL
        or not settings.AGENTOS_CANONICAL_AGENT_ID
        or not settings.PRIVY_APP_ID
        or not settings.PRIVY_APP_SECRET
        or not settings.PRIVY_AUTHORIZATION_PRIVATE_KEY
    ):
        return None

    # Local imports so unit tests that override this factory don't pay
    # the underlying SDK import cost.
    from src.policy.engine import (
        InstancePolicyEngine,
    )
    from src.runtime.agentos import AgentOSRuntime
    from src.services.privy_signing import (
        InvalidPrivyAuthorizationKeyError,
        PrivySigningService,
    )
    from src.services.wallet_service import WalletService

    # Task 41 fixpack F3 — Privy readiness hardening. A non-empty but
    # corrupt PEM (e.g. Coolify "developer mode" placeholder text
    # accidentally exported into .env) used to slip past the env-empty
    # check above and surface as an unhandled 500 from
    # `PrivySigningService.__init__`. Translate construction failure
    # into a controlled None → endpoint returns 503. No key material
    # is logged here — `InvalidPrivyAuthorizationKeyError` is
    # envelope-only by design.
    try:
        signing = PrivySigningService(
            private_key_pem=settings.PRIVY_AUTHORIZATION_PRIVATE_KEY,
            app_id=settings.PRIVY_APP_ID,
        )
    except InvalidPrivyAuthorizationKeyError:
        return None
    wallet_service = WalletService(signing_service=signing)
    runtime = AgentOSRuntime(
        api_url=settings.AGENTOS_API_URL,
        auth_token=settings.AGENTOS_AUTH_TOKEN,
        canonical_agent_id=settings.AGENTOS_CANONICAL_AGENT_ID,
    )
    return InstanceService(
        db=db,
        policy_engine=InstancePolicyEngine(),
        wallet_service=wallet_service,
        runtime=runtime,
        hosted_wallet_policy_id=settings.HOSTED_WALLET_POLICY_ID,
        authorization_pubkey=settings.AUTHORIZATION_PUBKEY_B64,
    )


# ---------------------------------------------------------------------
# Task 23 — deploy request / response schemas
# ---------------------------------------------------------------------


class InstanceDeployRequest(BaseModel):
    """Body for POST /api/v1/instances/deploy.

    ``template_key`` selects the canonical template to deploy against.
    ``effective_config`` is the V2 5-field envelope (validated server-side
    by InstancePolicyEngine.validate_spec). ``consent`` is the 4-ack
    deployment consent dict hashed into a VerificationArtifact by
    InstanceService step 6.

    Note: ``owner_ref`` is NOT accepted from the client body. It is set
    server-side from the authenticated Privy user.
    """

    template_key: str
    effective_config: dict[str, Any]
    consent: dict[str, Any]


class InstanceDeployResponse(BaseModel):
    """Narrow public-safe response for POST /api/v1/instances/deploy.

    Excludes all private fields (hosted_wallet_ref, runtime_handle_json,
    consent_artifact_id, wallet_address, wallet_provider, instance_owner_ref).
    Frontend uses the three fields here to route the success / partial-saga UX.
    """

    instance_id: int
    status: str
    last_failure_reason: Optional[str] = None


@router.get("/{instance_id}")
async def get_instance_profile(
    instance_id: int,
    user: PrivyUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the owner's instance profile + instance-specific benchmark history."""
    instance = await db.get(AgentInstance, instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="Instance not found")

    if instance.instance_owner_ref != user.privy_user_id:
        raise HTTPException(status_code=403, detail="Not your instance")

    template = await db.get(AgentTemplate, instance.template_id)

    # Task 15 synthetic-key bridge. No benchmark attempt → no synthetic
    # agent row → empty runs/rank_history (honest, never inferred from
    # canonical-template aggregate reputation).
    synthetic_agent_id = (
        await db.execute(
            select(Agent.agent_id).where(
                Agent.privy_user_id == f"instance:{instance_id}",
                Agent.subject_type == "customized_instance",
            )
        )
    ).scalar_one_or_none()

    runs: list[dict] = []
    rank_history: list[dict] = []
    if synthetic_agent_id is not None:
        run_rows = (
            await db.execute(
                select(Run)
                .where(Run.agent_id == synthetic_agent_id)
                .order_by(Run.created_at.desc(), Run.run_id.desc())
            )
        ).scalars().all()
        runs = [
            {
                "run_id": r.run_id,
                "challenge_id": r.challenge_id,
                "status": r.status,
                "completion_status": r.completion_status,
                "invalid_reason": r.invalid_reason,
                "ending_value": r.ending_value,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in run_rows
        ]

        snap_rows = (
            await db.execute(
                select(RankSnapshot)
                .where(RankSnapshot.agent_id == synthetic_agent_id)
                .order_by(RankSnapshot.computed_at.desc())
            )
        ).scalars().all()
        rank_history = [
            {
                "snapshot_id": s.snapshot_id,
                "score": s.score,
                "rank_version": s.rank_version,
                "subject_type": s.subject_type,
                "wins": s.wins,
                "losses": s.losses,
                "completed_runs": s.completed_runs,
                "invalid_runs": s.invalid_runs,
                "computed_at": s.computed_at.isoformat() if s.computed_at else None,
            }
            for s in snap_rows
        ]

    return {
        "instance_id": instance.instance_id,
        "template_key": template.template_key if template is not None else None,
        "template_version_at_deploy": instance.template_version_at_deploy,
        "effective_config": json.loads(instance.effective_config_json),
        "trust_label": instance.trust_label,
        "status": instance.status,
        "last_failure_reason": instance.last_failure_reason,
        "superseded_by_instance_id": instance.superseded_by_instance_id,
        "is_superseded": instance.superseded_by_instance_id is not None,
        "created_at": instance.created_at.isoformat() if instance.created_at else None,
        "benchmarked": len(runs) > 0,
        "runs": runs,
        "rank_history": rank_history,
    }


# ---------------------------------------------------------------------
# Task 23 — POST /api/v1/instances/deploy
# ---------------------------------------------------------------------


@router.post("/deploy", response_model=InstanceDeployResponse)
async def deploy_instance(
    body: InstanceDeployRequest,
    user: PrivyUser = Depends(get_current_user),
    service: Optional[InstanceService] = Depends(get_instance_service),
) -> InstanceDeployResponse:
    """Deploy a new hosted instance for the authenticated user.

    Owner is set server-side from the authenticated Privy user's
    ``privy_user_id`` — client-supplied owner fields are ignored.

    Returns a narrow 3-field response with no private fields
    (hosted_wallet_ref, runtime_handle_json, consent_artifact_id,
    wallet_address, wallet_provider, instance_owner_ref are NEVER
    serialized). Partial-saga failures (``*_failed`` status) return
    200 with `last_failure_reason` populated so the frontend can
    surface the operator-repair path via Task 14.

    Pre-row failures raise `InstanceDeployError` which maps to 400
    with the diagnostic in the detail string. When the deploy stack
    is unconfigured (missing env vars), returns 503.
    """
    if service is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Deploy stack not configured. Missing one of: "
                "HOSTED_WALLET_POLICY_ID, AUTHORIZATION_PUBKEY_B64, "
                "AGENTOS_API_URL, AGENTOS_CANONICAL_AGENT_ID, "
                "PRIVY_APP_ID, PRIVY_APP_SECRET, "
                "PRIVY_AUTHORIZATION_PRIVATE_KEY."
            ),
        )

    try:
        instance = await service.deploy_instance(
            template_key=body.template_key,
            effective_config=body.effective_config,
            consent=body.consent,
            owner_ref=user.privy_user_id,  # server-side, never from body
        )
    except InstanceDeployError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Deploy validation failed: {exc.details}",
        ) from exc

    return InstanceDeployResponse(
        instance_id=instance.instance_id,
        status=instance.status,
        last_failure_reason=instance.last_failure_reason,
    )

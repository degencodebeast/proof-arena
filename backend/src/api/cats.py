"""Wallet Safety Cat — read-only HTTP router."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user
from src.db.engine import get_db
from src.integrity.cats.wallet_safety import (
    InstanceUnresolvableError,
    RunNotFinalError,
    RunNotFoundError,
    UnsupportedProviderTypeError,
    UnsupportedTrustLabelError,
    compute_wallet_safety_cat,
    resolve_run_and_instance,
)

router = APIRouter(prefix="/cats")
_optional_bearer = HTTPBearer(auto_error=False)


def _map_domain_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, RunNotFoundError):
        return JSONResponse(status_code=404, content={"error": "run_not_found"})
    if isinstance(exc, InstanceUnresolvableError):
        return JSONResponse(status_code=404, content={"error": "instance_unresolvable"})
    if isinstance(exc, RunNotFinalError):
        return JSONResponse(
            status_code=422,
            content={"error": "run_not_final", "lifecycle_status": exc.lifecycle_status},
        )
    if isinstance(exc, UnsupportedProviderTypeError):
        return JSONResponse(
            status_code=422,
            content={"error": "unsupported_provider_type", "provider_type": exc.provider_type},
        )
    if isinstance(exc, UnsupportedTrustLabelError):
        return JSONResponse(
            status_code=422,
            content={"error": "unsupported_trust_label", "trust_label": exc.trust_label},
        )
    raise exc


@router.get("/wallet_safety/{run_id}")
async def get_wallet_safety_cat(
    run_id: int,
    creds: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: AsyncSession = Depends(get_db),
):
    """Read-only Cat verdict for a single completed run.

    Auth contract — keyed by AgentInstance.trust_label, NOT Agent.subject_type:
    - benchmarked_canonical_template → public, no auth.
    - benchmark_compatible_customized_instance → owner-auth via get_current_user.
    - external_custom_runtime → defensive 422 (caught by resolver).
    """
    try:
        try:
            run, agent, instance = await resolve_run_and_instance(db, run_id)
        except (
            RunNotFoundError, InstanceUnresolvableError, RunNotFinalError,
            UnsupportedProviderTypeError, UnsupportedTrustLabelError,
        ) as e:
            return _map_domain_error(e)

        # Per spec §8: owner auth is via auth.get_current_user. We delegate fully
        # to that public surface; do NOT reach into private _derive_identity.
        # get_current_user raises 401 itself on missing/empty bearer.
        if instance.trust_label == "benchmark_compatible_customized_instance":
            user = await get_current_user(creds)
            if user.privy_user_id != instance.instance_owner_ref:
                return JSONResponse(
                    status_code=403, content={"error": "not_instance_owner"},
                )
        # benchmarked_canonical_template → public; external_custom_runtime → already 422'd by resolver.

        return await compute_wallet_safety_cat(db, run_id)
    except HTTPException:
        # Let FastAPI's auth-layer 401 / explicit aborts propagate unmodified.
        raise
    except Exception:
        # Spec §8: 5xx must never leak free-text. Locked body, no detail / no
        # stack trace. Internal exception text must NOT appear in the response.
        return JSONResponse(status_code=500, content={"error": "internal_error"})

"""Public Verifier V0 — read-only HTTP router.

Auth contract — keyed by AgentInstance.trust_label, NOT Agent.subject_type:
- benchmarked_canonical_template       → public, no auth.
- benchmark_compatible_customized_instance → owner-auth via get_current_user.
- external_custom_runtime              → defensive 422 (caught by resolver).

5xx hardening: any unexpected exception collapses to {"error": "internal_error"}.
HTTPException is re-raised so get_current_user's auth-layer 401 propagates
unmodified.
"""
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
    resolve_run_and_instance,
)
from src.integrity.verifier.builder import build_verifier_run_response

router = APIRouter(prefix="/verifier")
_optional_bearer = HTTPBearer(auto_error=False)


def _map_domain_error(exc: Exception) -> JSONResponse:
    """Map Cat-module domain exceptions to spec'd JSON error bodies.

    Mirrors src/api/cats.py::_map_domain_error byte-for-byte. Duplicated
    here intentionally so the Verifier and Cat error contracts can be
    audited independently. Both must agree per spec §8.
    """
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


@router.get("/runs/{run_id}")
async def get_verifier_run(
    run_id: int,
    creds: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: AsyncSession = Depends(get_db),
):
    try:
        try:
            run, agent, instance = await resolve_run_and_instance(db, run_id)
        except (
            RunNotFoundError, InstanceUnresolvableError, RunNotFinalError,
            UnsupportedProviderTypeError, UnsupportedTrustLabelError,
        ) as e:
            return _map_domain_error(e)

        if instance.trust_label == "benchmark_compatible_customized_instance":
            user = await get_current_user(creds)
            if user.privy_user_id != instance.instance_owner_ref:
                return JSONResponse(
                    status_code=403, content={"error": "not_instance_owner"},
                )

        return await build_verifier_run_response(db, run_id)
    except HTTPException:
        # Auth-layer 401 from get_current_user must propagate unmodified.
        raise
    except Exception:
        # Spec §8: locked 5xx body. Internal exception text never leaks.
        return JSONResponse(status_code=500, content={"error": "internal_error"})

"""Wallet Safety Cat — read-only HTTP router."""
from __future__ import annotations
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_db
from src.integrity.cats.wallet_safety import (
    compute_wallet_safety_cat,
    InstanceUnresolvableError,
    RunNotFinalError,
    RunNotFoundError,
    UnsupportedProviderTypeError,
    UnsupportedTrustLabelError,
)

router = APIRouter(prefix="/cats")


@router.get("/wallet_safety/{run_id}")
async def get_wallet_safety_cat(run_id: int, db: AsyncSession = Depends(get_db)):
    """Read-only Cat verdict for a single completed run.

    Auth gate is added in Task 16 — Task 15 ships the public-canonical-template path only.
    """
    try:
        resp = await compute_wallet_safety_cat(db, run_id)
    except RunNotFoundError:
        return JSONResponse(status_code=404, content={"error": "run_not_found"})
    except InstanceUnresolvableError:
        return JSONResponse(status_code=404, content={"error": "instance_unresolvable"})
    except RunNotFinalError as e:
        return JSONResponse(
            status_code=422,
            content={"error": "run_not_final", "lifecycle_status": e.lifecycle_status},
        )
    except UnsupportedProviderTypeError as e:
        return JSONResponse(
            status_code=422,
            content={"error": "unsupported_provider_type", "provider_type": e.provider_type},
        )
    except UnsupportedTrustLabelError as e:
        return JSONResponse(
            status_code=422,
            content={"error": "unsupported_trust_label", "trust_label": e.trust_label},
        )
    return resp

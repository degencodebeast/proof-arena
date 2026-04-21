"""Admin endpoints — challenge management. Requires admin auth.

Fail-closed invariant: both endpoints resolve the program client via
`get_program_client()` and inject it into ChallengeService. If configuration
is incomplete (missing PROGRAM_ID, missing/invalid AUTHORITY_KEYPAIR_PATH),
the factory returns None and ChallengeService._require_program() raises
OnchainError — surfaced here as HTTP 502. No silent DB-only state transitions.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import PrivyUser, require_admin
from src.chain import get_program_client
from src.db.engine import get_db
from src.db.schemas import ChallengeCreateRequest
from src.services.challenge_service import ChallengeService, OnchainError

router = APIRouter(prefix="/admin")


@router.post("/challenges")
async def create_challenge(
    request: ChallengeCreateRequest,
    admin: PrivyUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new challenge. Admin only."""
    svc = ChallengeService(db, program_client=get_program_client())
    try:
        challenge = await svc.create_challenge(
            challenge_type=request.challenge_type,
            starting_usdc=request.starting_usdc,
            swap_intents=request.swap_intents,
            allowed_routes=request.allowed_routes,
            max_slippage_bps=request.max_slippage_bps,
            iteration_budget=request.iteration_budget,
            time_budget_secs=request.time_budget_secs,
            llm_provider=request.llm_provider,
            llm_model=request.llm_model,
            contestant_agent_ids=request.contestant_agent_ids,
        )
        return {"challenge_id": challenge.challenge_id, "status": challenge.status}
    except OnchainError as e:
        raise HTTPException(status_code=502, detail=e.detail) from e


@router.post("/challenges/{challenge_id}/start")
async def start_challenge(
    challenge_id: int,
    admin: PrivyUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Start a pending challenge. Admin only."""
    svc = ChallengeService(db, program_client=get_program_client())
    try:
        challenge = await svc.start_challenge(challenge_id)
        return {"challenge_id": challenge.challenge_id, "status": challenge.status}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except OnchainError as e:
        raise HTTPException(status_code=502, detail=e.detail) from e

"""Strategy submission endpoint with auth and anti-spam."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import PrivyUser, get_current_user
from src.config import settings
from src.db.engine import get_db
from src.db.schemas import StrategySubmitRequest, StrategyResponse
from src.services.strategy_service import StrategyService

router = APIRouter()


@router.post("/strategies", response_model=StrategyResponse)
async def submit_strategy(
    request: StrategySubmitRequest,
    user: PrivyUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrategyResponse:
    """Submit a new strategy. Requires authentication."""
    svc = StrategyService(db)

    # Anti-spam check
    active_count = await svc.get_active_count(user.privy_user_id)
    if active_count >= settings.MAX_SUBMISSIONS_PER_USER:
        raise HTTPException(
            status_code=429,
            detail=f"Maximum {settings.MAX_SUBMISSIONS_PER_USER} active strategies per user",
        )

    try:
        agent = await svc.register_strategy(
            privy_user_id=user.privy_user_id,
            owner_wallet=user.wallet_address or "",
            display_name=request.agent_name,
            system_prompt=request.system_prompt,
            config_json=request.config,
        )
        return StrategyResponse(
            agent_id=agent.agent_id,
            display_name=agent.display_name,
            submission_hash=agent.submission_hash,
            onchain_address=agent.onchain_address,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

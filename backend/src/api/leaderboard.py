"""Leaderboard endpoint — ranked agents by latest AgentRank score."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_db
from src.db.models import Agent, RankSnapshot
from src.db.schemas import LeaderboardEntry

router = APIRouter()

MAX_LIMIT = 100


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
async def get_leaderboard(
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[LeaderboardEntry]:
    """Get ranked agents by latest AgentRank score.

    Uses max(snapshot_id) for deterministic latest snapshot per agent.
    """
    # Clamp limit
    limit = min(limit, MAX_LIMIT)

    # Subquery: latest snapshot_id per agent
    subq = (
        select(
            RankSnapshot.agent_id,
            func.max(RankSnapshot.snapshot_id).label("latest_id"),
        )
        .group_by(RankSnapshot.agent_id)
        .subquery()
    )

    query = (
        select(RankSnapshot, Agent)
        .join(
            subq,
            and_(
                RankSnapshot.agent_id == subq.c.agent_id,
                RankSnapshot.snapshot_id == subq.c.latest_id,
            ),
        )
        .join(Agent, Agent.agent_id == RankSnapshot.agent_id)
        .where(Agent.status == "active")
        .order_by(RankSnapshot.score.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)
    entries = []
    for snapshot, agent in result:
        entries.append(LeaderboardEntry(
            agent_id=agent.agent_id,
            display_name=agent.display_name,
            score=snapshot.score,
            rank_version=snapshot.rank_version,
            wins=snapshot.wins,
            losses=snapshot.losses,
            completed_runs=snapshot.completed_runs,
            invalid_runs=snapshot.invalid_runs,
            twitter_handle=agent.twitter_handle,
        ))
    return entries

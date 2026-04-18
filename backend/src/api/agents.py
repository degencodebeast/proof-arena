"""Agent profile endpoint."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_db
from src.db.models import Agent, RankSnapshot, Run
from src.db.schemas import AgentProfileResponse, LeaderboardEntry, RunSummary

router = APIRouter()


@router.get("/agents/{agent_id}", response_model=AgentProfileResponse)
async def get_agent_profile(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
) -> AgentProfileResponse:
    """Get full agent profile with rank, recent runs, and score breakdown."""
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # Latest rank snapshot (by snapshot_id, not timestamp)
    rank_result = await db.execute(
        select(RankSnapshot)
        .where(RankSnapshot.agent_id == agent_id)
        .order_by(RankSnapshot.snapshot_id.desc())
        .limit(1)
    )
    latest_rank = rank_result.scalar_one_or_none()

    current_rank = None
    score_breakdown = {}
    if latest_rank:
        current_rank = LeaderboardEntry(
            agent_id=agent_id,
            display_name=agent.display_name,
            score=latest_rank.score,
            rank_version=latest_rank.rank_version,
            wins=latest_rank.wins,
            losses=latest_rank.losses,
            completed_runs=latest_rank.completed_runs,
            invalid_runs=latest_rank.invalid_runs,
            twitter_handle=agent.twitter_handle,
        )
        try:
            score_breakdown = json.loads(latest_rank.score_breakdown_json)
        except (json.JSONDecodeError, TypeError):
            pass

    # Recent runs (limit 10)
    runs_result = await db.execute(
        select(Run)
        .where(Run.agent_id == agent_id)
        .order_by(Run.created_at.desc())
        .limit(10)
    )
    recent_runs = [
        RunSummary(
            run_id=r.run_id,
            challenge_id=r.challenge_id,
            status=r.status,
            completion_status=r.completion_status,
            starting_value=r.starting_value,
            ending_value=r.ending_value,
        )
        for r in runs_result.scalars()
    ]

    return AgentProfileResponse(
        agent_id=agent.agent_id,
        display_name=agent.display_name,
        owner_wallet=agent.owner_wallet,
        submission_hash=agent.submission_hash,
        twitter_handle=agent.twitter_handle,
        current_rank=current_rank,
        recent_runs=recent_runs,
        score_breakdown=score_breakdown,
    )

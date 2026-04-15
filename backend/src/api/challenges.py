"""Challenge endpoints — list, detail, events."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_db
from src.db.models import Challenge, Run, RunEvent
from src.db.schemas import (
    ChallengeSummary,
    ChallengeDetailResponse,
    ContestantSummary,
    RunEventSummary,
)

router = APIRouter()


@router.get("/challenges", response_model=list[ChallengeSummary])
async def list_challenges(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[ChallengeSummary]:
    query = select(Challenge).order_by(Challenge.created_at.desc()).offset(offset).limit(limit)
    if status:
        query = query.where(Challenge.status == status)
    result = await db.execute(query)
    return [
        ChallengeSummary(
            challenge_id=c.challenge_id,
            challenge_type=c.challenge_type,
            challenge_version=c.challenge_version,
            status=c.status,
            num_contestants=c.num_contestants,
            num_finalized=c.num_finalized,
            started_at=c.started_at,
            ended_at=c.ended_at,
        )
        for c in result.scalars()
    ]


@router.get("/challenges/{challenge_id}", response_model=ChallengeDetailResponse)
async def get_challenge(
    challenge_id: int,
    db: AsyncSession = Depends(get_db),
) -> ChallengeDetailResponse:
    challenge = await db.get(Challenge, challenge_id)
    if challenge is None:
        raise HTTPException(status_code=404, detail=f"Challenge {challenge_id} not found")

    # Get contestants with single join (no N+1)
    from src.db.models import Agent
    runs_result = await db.execute(
        select(Run, Agent)
        .outerjoin(Agent, Agent.agent_id == Run.agent_id)
        .where(Run.challenge_id == challenge_id)
    )
    contestants = []
    for run, agent in runs_result:
        contestants.append(ContestantSummary(
            agent_id=run.agent_id,
            display_name=agent.display_name if agent else f"Agent {run.agent_id}",
            run_id=run.run_id,
            status=run.status,
            completion_status=run.completion_status,
            ending_value=run.ending_value,
        ))

    import json
    config = {}
    try:
        config = json.loads(challenge.config_json)
    except (json.JSONDecodeError, TypeError):
        pass

    return ChallengeDetailResponse(
        challenge_id=challenge.challenge_id,
        challenge_type=challenge.challenge_type,
        challenge_version=challenge.challenge_version,
        llm_provider=challenge.llm_provider,
        llm_model=challenge.llm_model,
        status=challenge.status,
        config=config,
        num_contestants=challenge.num_contestants,
        num_finalized=challenge.num_finalized,
        winner_agent_id=challenge.winner_agent_id,
        contestants=contestants,
        created_at=challenge.created_at,
        started_at=challenge.started_at,
        ended_at=challenge.ended_at,
    )


@router.get("/challenges/{challenge_id}/events", response_model=list[RunEventSummary])
async def get_challenge_events(
    challenge_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[RunEventSummary]:
    # Verify challenge exists
    challenge = await db.get(Challenge, challenge_id)
    if challenge is None:
        raise HTTPException(status_code=404, detail=f"Challenge {challenge_id} not found")

    # Get all runs for the challenge, then their events
    runs_result = await db.execute(
        select(Run.run_id).where(Run.challenge_id == challenge_id)
    )
    run_ids = [r for (r,) in runs_result]

    if not run_ids:
        return []

    events_result = await db.execute(
        select(RunEvent)
        .where(RunEvent.run_id.in_(run_ids))
        .order_by(RunEvent.timestamp.asc(), RunEvent.run_id.asc(), RunEvent.sequence_no.asc())
        .limit(limit)
    )
    return [
        RunEventSummary(
            event_id=e.event_id,
            run_id=e.run_id,
            sequence_no=e.sequence_no,
            event_type=e.event_type,
            timestamp=e.timestamp,
            tx_signature=e.tx_signature,
        )
        for e in events_result.scalars()
    ]

"""Leaderboard endpoint — ranked agents by latest AgentRank score.

Task 16: subject-partitioned reads. The endpoint accepts an optional
``subject`` query parameter that partitions results by the V2
subject-type contract:

- ``subject=canonical`` or omitted (backward-compat default) → return
  ``subject_type='canonical_template'`` rows. V1 clients see
  unchanged behavior (all pre-V2 agent rows were backfilled to
  ``canonical_template`` by the A-4 migration).
- ``subject=customized`` → return ``subject_type='customized_instance'``
  rows, excluding any Agent linked via Task 15's synthetic
  ``privy_user_id='instance:{id}'`` key to an ``AgentInstance`` with
  the reserved ``external_custom_runtime`` trust label.

Canonical and customized partitions are disjoint by construction.
The reserved ``external_custom_runtime`` trust label is never
assigned by any V2 code path, but the ``NOT EXISTS`` subquery on the
customized partition is defense-in-depth against future V2.1 code
that adds it.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_db
from src.db.models import Agent, AgentInstance, RankSnapshot
from src.db.schemas import LeaderboardEntry

router = APIRouter()

MAX_LIMIT = 100

# Map public `subject` query values to the A-4 subject_type values.
# Canonical is the default — backward-compat with the V1 Task 14 frontend.
_SUBJECT_MAP: dict[str, str] = {
    "canonical": "canonical_template",
    "customized": "customized_instance",
}


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
async def get_leaderboard(
    subject: Literal["canonical", "customized"] = Query(default="canonical"),
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[LeaderboardEntry]:
    """Get subject-partitioned ranked agents by latest AgentRank score.

    Uses max(snapshot_id) for deterministic latest-snapshot selection
    per agent within the requested subject partition.
    """
    # Clamp limit
    limit = min(limit, MAX_LIMIT)
    subject_type = _SUBJECT_MAP[subject]

    # Subquery: latest snapshot_id per agent, pre-filtered to the
    # requested subject_type so an agent with rows in both partitions
    # resolves to the correct "latest" per partition.
    subq = (
        select(
            RankSnapshot.agent_id,
            func.max(RankSnapshot.snapshot_id).label("latest_id"),
        )
        .where(RankSnapshot.subject_type == subject_type)
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
        .where(
            Agent.status == "active",
            Agent.subject_type == subject_type,
        )
    )

    # Defense-in-depth for the customized partition: exclude any Agent
    # whose synthetic key (`privy_user_id = f"instance:{id}"` from
    # Task 15) maps to an AgentInstance with the reserved
    # `external_custom_runtime` trust label. The label is not assigned
    # by any V2 code path today; the exclusion prevents future V2.1
    # code from silently leaking it into the public leaderboard.
    if subject == "customized":
        external_instance_exists = (
            select(AgentInstance.instance_id)
            .where(
                AgentInstance.trust_label == "external_custom_runtime",
                Agent.privy_user_id
                == ("instance:" + cast(AgentInstance.instance_id, String)),
            )
            .exists()
        )
        query = query.where(~external_instance_exists)

    query = (
        query.order_by(RankSnapshot.score.desc())
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

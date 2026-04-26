"""Task 20 — public flagship read endpoint.

``GET /api/v1/flagship`` returns the current live flagship
``AgentInstance`` plus recent unfiltered runs and an outcome-distribution
summary. Public (no auth token). Returns 404 when no live flagship
exists yet (pre-Task-18 bootstrap).

Honest about current state:

- Task 18 deploys the flagship hosted instance with
  ``trust_label='benchmarked_canonical_template'``.
- Task 19 cron creates pending runs every 6 hours (creation-only —
  hosted execution deferred behind the runner swap-service abstraction).
- This endpoint renders the pending rows faithfully. No over-claim of
  completed executions.

Evidence URLs are intentionally NOT included in the response — no
``/runs/{id}/evidence`` endpoint ships in the backend today, and
returning a placeholder URL would create broken public links. When the
evidence endpoint lands, ``evidence_url`` can be added to
``runs[*]`` objects without breaking existing consumers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_db
from src.services.flagship_service import (
    FlagshipService,
    compute_outcome_distribution,
)

router = APIRouter(prefix="/flagship", tags=["flagship"])


_RECENT_RUNS_LIMIT: int = 30


@router.get("")
async def get_flagship(db: AsyncSession = Depends(get_db)) -> dict:
    """Return the current live flagship state + recent unfiltered runs."""
    service = FlagshipService(db)
    flagship = await service.get_flagship_instance(template_key="swap_executor_v1")
    if flagship is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No live flagship instance. Run scripts/bootstrap_flagship.py "
                "then FlagshipService.deploy_flagship_instance() to bootstrap."
            ),
        )

    runs = await service.get_flagship_runs(
        flagship.instance_id, limit=_RECENT_RUNS_LIMIT
    )

    return {
        "instance_id": flagship.instance_id,
        "trust_label": flagship.trust_label,
        "template_key": "swap_executor_v1",
        "status_label": (
            "devnet-live" if flagship.status == "live" else "offline"
        ),
        "runs": [
            {
                "run_id": r.run_id,
                "status": r.status,
                "completion_status": r.completion_status,
                "invalid_reason": r.invalid_reason,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in runs
        ],
        "outcome_distribution": compute_outcome_distribution(runs),
    }

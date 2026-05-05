"""V2.1 Rebalance smoke seed — populates a known-good rebalance run + evidence
artifact so live curl smoke against /api/v1/cats/rebalance_policy/{run_id} and
/api/v1/verifier/runs/{run_id} returns a populated payload.

Spec §5.9 — DEMO SUPPORT, NOT CORE. Do not depend on this seed for any
production trust path. Idempotent on re-invocation.

HONESTY DISCLAIMER (V0 demo-vs-production gap):
This seed builds the rebalance_evidence_v1 artifact via tests._rebalance_helpers
(make_rebalance_evidence_payload), which uses a HAPPY-PATH PRICED FIXTURE —
synthetic 1_000_000 base-unit prices for every mint in the canonical universe.
That makes the demo Cat result a "pass" verdict.

Real V0 production runs would produce different artifact data:
- The runner's observe event (runner_service.execute_run) captures wallet
  balances but NOT prices, so prices_used would emit null for every mint.
- Per spec §5.6 line 211, price_data_present_check would FAIL on null entries.
- The Cat verdict on a real V0 run would be "fail" with
  price_data_present_check in the failing set.

This seed intentionally uses the happy-path fixture so the demo curl shows
a populated/passing Cat response. Adding a real price-observation pipeline
to the runner is future work (post-V0). The Cat predicate itself is correct;
the gap is in the runner's evidence emission, not the trust path.

Run: `python -m scripts.seed_v2_1_rebalance_smoke_run` from agent-rank/backend/.
"""
from __future__ import annotations

import asyncio


async def run(db) -> dict:
    """Build a known-good rebalance instance + completed run + evidence artifact.

    Returns: {"run_id": int, "evidence_artifact_id": int, "evidence_content_hash": str}.
    """
    from tests._rebalance_helpers import (
        make_completed_rebalance_run, make_rebalance_instance,
    )
    template, instance, agent = await make_rebalance_instance(
        db,
        owner_ref="instance:smoke-demo",
        trust_label="benchmarked_canonical_template",  # public — no auth needed for demo curl.
    )
    run_row = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
    )
    from sqlalchemy import select
    from src.db.models import VerificationArtifact
    artifact = (await db.execute(
        select(VerificationArtifact).where(
            VerificationArtifact.run_id == run_row.run_id,
            VerificationArtifact.artifact_type == "rebalance_evidence_v1",
        )
    )).scalar_one()
    return {
        "run_id": run_row.run_id,
        "evidence_artifact_id": artifact.artifact_id,
        "evidence_content_hash": artifact.content_hash,
    }


def main():
    """Entrypoint for `python -m scripts.seed_v2_1_rebalance_smoke_run`.

    Uses a real DB session via src.db.engine. Operator must have DATABASE_URL
    configured in env (per existing v2_demo.md docker-compose conventions).
    """
    from src.db.engine import async_session_factory

    async def _go():
        async with async_session_factory() as db:
            result = await run(db)
            await db.commit()
            print(result)

    asyncio.run(_go())


if __name__ == "__main__":
    main()

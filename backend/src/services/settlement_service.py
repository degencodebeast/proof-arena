"""SettlementService — settlement orchestration and rank computation.

Orchestrates over verified Task 7-9 outputs. Does NOT duplicate
RunnerService finalization or RunAuditor evidence hashing.

Rank formula is PROVISIONAL V1:
  win_rate * 0.35 + execution_quality * 0.30 + consistency * 0.20 + confidence * 0.15
"""

from __future__ import annotations

import hashlib
import json
import logging
import statistics
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.chain.program_client import AgentArenaClient
from src.config import settings
from src.db.models import Agent, Challenge, RankSnapshot, Run, VerificationArtifact
from src.integrity.settlement_verifier import SettlementVerifier
from src.integrity.subject_types import SubjectType
from src.services.serialization import serialize_payload

logger = logging.getLogger(__name__)

RANK_WEIGHTS_V1 = {
    "win_rate": 0.35,
    "execution_quality": 0.30,
    "consistency": 0.20,
    "confidence": 0.15,
}


class SettlementError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"Settlement failed: {detail}")


class SettlementService:
    """Orchestrates challenge settlement and participant ranking."""

    def __init__(
        self,
        db: AsyncSession,
        program_client: AgentArenaClient | None = None,
    ):
        self.db = db
        self.program = program_client

    async def settle_challenge(self, challenge_id: int) -> Challenge:
        """Main orchestration: verify → winner → on-chain → update → rank.

        Requires program client — settlement must be anchored on-chain.
        """
        # Fix 1: Require program client
        if self.program is None:
            raise SettlementError(
                "No program client configured. Settlement requires on-chain anchoring."
            )

        # Fix 3: Idempotency — reject already-settled challenges
        challenge = await self.db.get(Challenge, challenge_id)
        if challenge is None:
            raise SettlementError(f"Challenge {challenge_id} not found")
        if challenge.status == "completed" or challenge.winner_agent_id is not None:
            raise SettlementError(
                f"Challenge {challenge_id} already settled "
                f"(status={challenge.status}, winner={challenge.winner_agent_id})"
            )

        verifier = SettlementVerifier(self.db)

        # 1. Verify eligibility
        eligibility = await verifier.verify_settlement_eligibility(challenge_id)
        if not eligibility.can_settle:
            raise SettlementError(
                f"Cannot settle challenge {challenge_id}: "
                f"eligible={len(eligibility.eligible)}, "
                f"terminal={eligibility.all_terminal}, "
                f"cardinality={eligibility.cardinality_met}"
            )

        # 2. Select winner
        winner = SettlementVerifier.determine_winner(eligibility.eligible)

        # Fix 4 + Task 27: require on-chain RunAccount PDAs only for V1/local
        # runs. Task 15 hosted-instance runs intentionally have
        # onchain_address=None (V2 plan §3: zero new Anchor work for hosted
        # runs). Pre-Task-27, the universal check blocked the hosted path
        # from ever reaching _update_ranks. We partition by provider_type and
        # reject mixed-provider challenges explicitly (not a V2 production
        # path).
        all_runs = eligibility.eligible + [r for r, _ in eligibility.ineligible]
        local_runs_for_settle = [
            r for r in all_runs if r.provider_type != "hosted_instance"
        ]
        hosted_runs_for_settle = [
            r for r in all_runs if r.provider_type == "hosted_instance"
        ]
        if local_runs_for_settle and hosted_runs_for_settle:
            raise SettlementError(
                f"Challenge {challenge_id} has mixed provider_type runs "
                f"(local={len(local_runs_for_settle)}, "
                f"hosted={len(hosted_runs_for_settle)}); "
                "V2 settlement is single-kind per challenge"
            )

        if winner is not None and local_runs_for_settle:
            from solders.pubkey import Pubkey

            run_pdas = []
            for run in local_runs_for_settle:
                if not run.onchain_address:
                    raise SettlementError(
                        f"Run {run.run_id} (agent {run.agent_id}) missing on-chain address"
                    )
                run_pdas.append(Pubkey.from_string(run.onchain_address))

            # 3. On-chain settle (V1 path only)
            try:
                settle_tx = await self.program.settle_challenge(challenge_id, run_pdas)
            except Exception as e:
                raise SettlementError(f"On-chain settle failed: {e}") from e

            # Record chain tx as same-transaction evidence artifact.
            # NOTE: This artifact is NOT durable until final commit().
            # If later DB writes (challenge update, rank snapshots) fail and
            # the session rolls back, this artifact is lost. The on-chain
            # settlement is still real — reconciliation must detect already-
            # settled on-chain state by querying the ChallengeAccount directly.
            onchain_ref = serialize_payload({
                "challenge_id": challenge_id,
                "tx_signature": str(settle_tx),
                "winner_agent_id": winner.agent_id if winner else None,
            })
            self.db.add(VerificationArtifact(
                run_id=winner.run_id if winner else local_runs_for_settle[0].run_id,
                artifact_type="onchain_settle",
                uri_or_ref=onchain_ref,
                content_hash=hashlib.sha256(onchain_ref.encode()).hexdigest(),
            ))
            await self.db.flush()  # Ordered before subsequent writes, not independently durable
        # else: all-hosted V2 settlement. No on-chain settle call, no
        # onchain_settle artifact. The settlement_record artifact created by
        # verifier.create_settlement_record(...) below remains the off-chain
        # evidence anchor. _update_ranks still runs per Task 27 routing.

        # 4. Update Challenge row
        challenge.winner_agent_id = winner.agent_id if winner else None
        challenge.status = "completed"
        challenge.ended_at = datetime.now(timezone.utc)

        # 5. Settlement artifact
        if winner is not None:
            await verifier.create_settlement_record(
                challenge_id, winner, eligibility.eligible,
            )

        # 6. Rank updates for ALL participants
        await self._update_ranks(
            winner.agent_id if winner else None, all_runs,
        )

        await self.db.commit()
        return challenge

    async def _update_ranks(
        self,
        winner_agent_id: int | None,
        challenge_runs: list[Run],
    ) -> None:
        """Update ranks for all participants. Append-only snapshots."""
        agent_ids = list({r.agent_id for r in challenge_runs})
        if not agent_ids:
            return

        # Batch-fetch all terminal runs for ranking (completed, failed, timeout)
        terminal_statuses = ["completed", "failed", "timeout"]
        result = await self.db.execute(
            select(Run)
            .where(Run.agent_id.in_(agent_ids))
            .where(Run.status.in_(terminal_statuses))
        )
        all_historical = list(result.scalars().all())

        runs_by_agent: dict[int, list[Run]] = {}
        for run in all_historical:
            runs_by_agent.setdefault(run.agent_id, []).append(run)

        # Task 27: per-agent provider_type map derived from this challenge's
        # runs. Routes RankSnapshot.subject_type and gates the canonical
        # on-chain update so hosted_instance runs never mutate canonical
        # AgentRankAccount state. uq_runs_challenge_agent guarantees at most
        # one run per agent per challenge, so this map is single-valued.
        provider_by_agent: dict[int, str] = {
            run.agent_id: run.provider_type for run in challenge_runs
        }

        # Map agent_id → run_id from challenge runs for artifact anchoring
        run_id_by_agent: dict[int, int] = {}
        for run in challenge_runs:
            run_id_by_agent[run.agent_id] = run.run_id

        win_counts = await self._get_latest_wins_batch(agent_ids)

        # Fix 2: Batch-load Agent rows for strategy PDAs
        agents_by_id: dict[int, Agent] = {}
        if self.program is not None:
            agent_result = await self.db.execute(
                select(Agent).where(Agent.agent_id.in_(agent_ids))
            )
            for agent in agent_result.scalars().all():
                agents_by_id[agent.agent_id] = agent

        for agent_id in agent_ids:
            agent_runs = runs_by_agent.get(agent_id, [])
            is_winner = agent_id == winner_agent_id
            prev_wins = win_counts.get(agent_id, 0)

            rank_data = self._compute_rank(
                agent_id, is_winner, agent_runs, prev_wins,
            )

            # Task 27: route subject_type from this challenge's provider_type
            # so customized-instance reputation never blends into the
            # canonical leaderboard (Task 16 read-side partition).
            provider_type = provider_by_agent.get(agent_id, "local")
            is_hosted_instance = provider_type == "hosted_instance"
            subject_type = (
                SubjectType.CUSTOMIZED_INSTANCE.value
                if is_hosted_instance
                else SubjectType.CANONICAL_TEMPLATE.value
            )

            snapshot = RankSnapshot(
                agent_id=agent_id,
                rank_version=settings.RANK_VERSION,
                app_version=settings.APP_VERSION,
                score=rank_data["score"],
                score_inputs_json=serialize_payload(rank_data["inputs"]),
                score_breakdown_json=serialize_payload(rank_data["breakdown"]),
                wins=rank_data["wins"],
                losses=rank_data["losses"],
                completed_runs=rank_data["completed_runs"],
                invalid_runs=rank_data["invalid_runs"],
                subject_type=subject_type,
                computed_at=datetime.now(timezone.utc),
            )
            self.db.add(snapshot)

            # Task 27: hosted_instance runs never mutate canonical on-chain
            # reputation. Off-chain snapshot above is the only rank artifact
            # for this agent; skip the V1 canonical-update branch entirely
            # (including its rank_sync_failed reconciliation artifact).
            if is_hosted_instance:
                continue

            # On-chain rank update with real strategy PDA
            if self.program is not None:
                agent = agents_by_id.get(agent_id)
                if agent and agent.onchain_address:
                    try:
                        from solders.pubkey import Pubkey
                        strategy_pda = Pubkey.from_string(agent.onchain_address)
                        await self.program.update_agent_rank(
                            agent_id=agent_id,
                            strategy_pda=strategy_pda,
                            score=int(rank_data["score"] * 100),
                            rank_version=1,
                            wins=rank_data["wins"],
                            losses=rank_data["losses"],
                            total_challenges=rank_data["total_runs"],
                            avg_execution_quality=int(rank_data["breakdown"]["execution_quality"]["value"] * 100),
                            consistency=int(rank_data["breakdown"]["consistency"]["value"] * 100),
                            invalid_runs=rank_data["invalid_runs"],
                        )
                    except Exception as e:
                        logger.error("On-chain rank update failed for agent %d: %s", agent_id, e)
                        artifact_ref = serialize_payload({
                            "agent_id": agent_id,
                            "error": str(e),
                            "score": rank_data["score"],
                        })
                        self.db.add(VerificationArtifact(
                            run_id=run_id_by_agent[agent_id],
                            artifact_type="rank_sync_failed",
                            uri_or_ref=artifact_ref,
                            content_hash=hashlib.sha256(artifact_ref.encode()).hexdigest(),
                        ))
                else:
                    logger.warning("Agent %d missing on-chain address, skipping on-chain rank update", agent_id)
                    artifact_ref = serialize_payload({
                        "agent_id": agent_id,
                        "reason": "missing_onchain_address",
                    })
                    self.db.add(VerificationArtifact(
                        run_id=run_id_by_agent[agent_id],
                        artifact_type="rank_sync_failed",
                        uri_or_ref=artifact_ref,
                        content_hash=hashlib.sha256(artifact_ref.encode()).hexdigest(),
                    ))

        await self.db.flush()

    async def _get_latest_wins_batch(self, agent_ids: list[int]) -> dict[int, int]:
        """Get latest win count per agent in one query.

        Uses max(snapshot_id) for deterministic ordering — no timestamp tie ambiguity.
        """
        from sqlalchemy import and_

        subq = (
            select(
                RankSnapshot.agent_id,
                func.max(RankSnapshot.snapshot_id).label("latest_id"),
            )
            .where(RankSnapshot.agent_id.in_(agent_ids))
            .group_by(RankSnapshot.agent_id)
            .subquery()
        )

        result = await self.db.execute(
            select(RankSnapshot.agent_id, RankSnapshot.wins)
            .join(
                subq,
                and_(
                    RankSnapshot.agent_id == subq.c.agent_id,
                    RankSnapshot.snapshot_id == subq.c.latest_id,
                ),
            )
        )

        wins: dict[int, int] = {aid: 0 for aid in agent_ids}
        for row in result:
            wins[row[0]] = row[1]
        return wins

    @staticmethod
    def _compute_rank(
        agent_id: int,
        is_winner: bool,
        all_runs: list[Run],
        prev_wins: int,
    ) -> dict[str, Any]:
        """Compute rank from historical runs. Provisional V1 formula."""
        total = len(all_runs)
        completed = sum(1 for r in all_runs if r.completion_status == "complete")
        invalid = sum(1 for r in all_runs if r.completion_status == "invalid")

        wins = prev_wins + (1 if is_winner else 0)
        losses = total - wins

        exec_qualities: list[float] = []
        for run in all_runs:
            if run.score_inputs_json:
                try:
                    inputs = json.loads(run.score_inputs_json)
                    exec_qualities.append(inputs.get("execution_quality", 1.0))
                except (json.JSONDecodeError, TypeError):
                    pass

        win_rate = (wins / total * 100) if total > 0 else 0.0
        avg_eq = (sum(exec_qualities) / len(exec_qualities) * 100) if exec_qualities else 50.0
        avg_eq = min(avg_eq, 100.0)

        if len(exec_qualities) >= 2:
            std_dev = statistics.stdev(exec_qualities)
            consistency = max(0.0, 100.0 - std_dev * 100)
        else:
            consistency = 50.0

        confidence = min(total * 10, 100)

        score = round(
            win_rate * RANK_WEIGHTS_V1["win_rate"]
            + avg_eq * RANK_WEIGHTS_V1["execution_quality"]
            + consistency * RANK_WEIGHTS_V1["consistency"]
            + confidence * RANK_WEIGHTS_V1["confidence"],
            2,
        )

        return {
            "score": score,
            "wins": wins,
            "losses": losses,
            "completed_runs": completed,
            "invalid_runs": invalid,
            "total_runs": total,
            "inputs": {
                "total_runs": total,
                "completed_runs": completed,
                "invalid_runs": invalid,
                "wins": wins,
                "losses": losses,
                "execution_qualities": exec_qualities,
                "is_current_winner": is_winner,
            },
            "breakdown": {
                "win_rate": {"value": round(win_rate, 2), "weight": RANK_WEIGHTS_V1["win_rate"]},
                "execution_quality": {"value": round(avg_eq, 2), "weight": RANK_WEIGHTS_V1["execution_quality"]},
                "consistency": {"value": round(consistency, 2), "weight": RANK_WEIGHTS_V1["consistency"]},
                "confidence": {"value": round(confidence, 2), "weight": RANK_WEIGHTS_V1["confidence"]},
            },
        }

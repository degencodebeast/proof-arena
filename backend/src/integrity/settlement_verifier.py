"""SettlementVerifier — settlement eligibility and winner determination.

Core invariant: incomplete or invalid runs can NEVER be eligible winners.
Ending balance alone does not determine validity.

This is an integrity helper only. Does NOT call on-chain settle, update
Challenge winner fields, or compute ranks. That belongs to Task 10.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Challenge, Run, VerificationArtifact
from src.services.serialization import serialize_payload as _serialize_payload


@dataclass
class SettlementEligibility:
    """Result of checking which runs are eligible for settlement."""

    eligible: list[Run] = field(default_factory=list)
    ineligible: list[tuple[Run, str]] = field(default_factory=list)
    expected_contestants: int = 0

    @property
    def total_runs(self) -> int:
        return len(self.eligible) + len(self.ineligible)

    @property
    def all_terminal(self) -> bool:
        """All runs are in a terminal state (completed/failed/timeout)."""
        terminal_statuses = {"completed", "failed", "timeout"}
        for run, _ in self.ineligible:
            if run.status not in terminal_statuses:
                return False
        return True

    @property
    def cardinality_met(self) -> bool:
        """Run count matches expected contestants."""
        if self.expected_contestants <= 0:
            return True
        return self.total_runs == self.expected_contestants

    @property
    def can_settle(self) -> bool:
        """Settlement requires: all terminal, cardinality met, eligible > 0."""
        return self.all_terminal and self.cardinality_met and len(self.eligible) > 0


class SettlementVerifier:
    """Verifies settlement eligibility and determines winners."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def verify_settlement_eligibility(
        self, challenge_id: int
    ) -> SettlementEligibility:
        """Check all runs for a challenge and classify eligibility.

        Also enforces cardinality: run count must match Challenge.num_contestants.
        """
        challenge = await self.db.get(Challenge, challenge_id)
        if not challenge:
            raise ValueError(f"Challenge {challenge_id} not found")

        result = await self.db.execute(
            select(Run).where(Run.challenge_id == challenge_id)
        )
        runs = list(result.scalars().all())

        # Check for duplicate agent_ids
        agent_ids = [r.agent_id for r in runs]
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError(
                f"Challenge {challenge_id} has duplicate agent runs: "
                f"{[a for a in agent_ids if agent_ids.count(a) > 1]}"
            )

        eligibility = SettlementEligibility()
        eligibility.expected_contestants = challenge.num_contestants

        for run in runs:
            reason = self._check_eligibility(run)
            if reason is None:
                eligibility.eligible.append(run)
            else:
                eligibility.ineligible.append((run, reason))

        return eligibility

    @staticmethod
    def _check_eligibility(run: Run) -> str | None:
        """Return ineligibility reason, or None if eligible."""
        if run.status != "completed":
            return f"not_completed:{run.status}"
        if run.completion_status != "complete":
            return f"not_valid:{run.completion_status}:{run.invalid_reason or 'unknown'}"
        if run.ending_value is None:
            return "missing_ending_value"
        if not run.run_log_hash:
            return "missing_run_log_hash"
        return None

    @staticmethod
    def determine_winner(eligible_runs: list[Run]) -> Run | None:
        """Determine winner from eligible runs.

        Rules:
        1. Highest ending_value wins.
        2. Tiebreak: earliest ended_at.
        3. If no eligible runs, return None.
        """
        if not eligible_runs:
            return None

        def sort_key(r: Run) -> tuple[int, float]:
            ev = r.ending_value if r.ending_value is not None else 0
            ea = r.ended_at.timestamp() if r.ended_at else float("inf")
            return (-ev, ea)

        sorted_runs = sorted(eligible_runs, key=sort_key)
        return sorted_runs[0]

    async def create_settlement_record(
        self, challenge_id: int, winner: Run, eligible_runs: list[Run],
    ) -> VerificationArtifact:
        """Create a settlement record as a VerificationArtifact.

        Requires a winner run — no-winner settlements should not create
        settlement records (there's nothing to settle).
        """
        payload = {
            "challenge_id": challenge_id,
            "winner_agent_id": winner.agent_id,
            "winner_ending_value": winner.ending_value,
            "total_eligible": len(eligible_runs),
            "settled_at": datetime.now(timezone.utc).isoformat(),
        }
        payload_json = _serialize_payload(payload)

        artifact = VerificationArtifact(
            run_id=winner.run_id,
            artifact_type="settlement_record",
            uri_or_ref=payload_json,
            content_hash=hashlib.sha256(payload_json.encode()).hexdigest(),
        )
        self.db.add(artifact)
        await self.db.flush()
        return artifact

"""RunAuditor — deterministic evidence hashing and verification artifact creation.

Uses the same canonical hash semantics as RunnerService._compute_run_log_hash.
Evidence boundary: loop events + flatten + finalize. Post-chain operational
events (onchain_finalize, on-chain error) are excluded.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Agent, Challenge, Run, RunEvent, VerificationArtifact
from src.services.serialization import EventJSONEncoder

# Post-chain event types excluded from evidence hash
POST_CHAIN_EVENT_TYPES = {"onchain_finalize"}


def _canonical_serialize(obj: Any) -> str:
    return json.dumps(obj, cls=EventJSONEncoder, sort_keys=True, separators=(",", ":"))


def _is_post_chain_error(event: RunEvent) -> bool:
    """Check if an error event is a post-chain operational event."""
    if event.event_type != "error":
        return False
    payload = event.result_payload_json
    if not payload:
        return False
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
        return bool(data.get("onchain_finalize_failed"))
    except (json.JSONDecodeError, TypeError, AttributeError):
        return False


def event_to_canonical_dict(event: RunEvent) -> dict[str, Any]:
    """Reconstruct canonical event dict from a persisted RunEvent row."""
    def _parse_json(s: str | None) -> Any:
        if s is None:
            return None
        try:
            return json.loads(s)
        except (json.JSONDecodeError, TypeError):
            return s

    return {
        "run_id": event.run_id,
        "sequence_no": event.sequence_no,
        "event_type": event.event_type,
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
        "state_snapshot_json": _parse_json(event.state_snapshot_json),
        "action_payload_json": _parse_json(event.action_payload_json),
        "validation_payload_json": _parse_json(event.validation_payload_json),
        "execution_payload_json": _parse_json(event.execution_payload_json),
        "result_payload_json": _parse_json(event.result_payload_json),
        "tx_signature": event.tx_signature,
        "quote_snapshot_ref": event.quote_snapshot_ref,
    }


def is_evidence_event_type(event_type: str) -> bool:
    """Check if an event type is inside the evidence hash boundary."""
    return event_type not in POST_CHAIN_EVENT_TYPES


def compute_evidence_hash(events: list[dict[str, Any]]) -> str:
    """Compute SHA-256 of events in deterministic order.

    Matches RunnerService._compute_run_log_hash exactly.
    """
    sorted_events = sorted(events, key=lambda e: e.get("sequence_no", 0))
    hasher = hashlib.sha256()
    for event in sorted_events:
        event_bytes = _canonical_serialize(event).encode("utf-8")
        hasher.update(event_bytes)
    return hasher.hexdigest()


class RunAuditor:
    """Generates run evidence hashes and verification artifacts."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_ordered_events(self, run_id: int) -> list[RunEvent]:
        result = await self.db.execute(
            select(RunEvent)
            .where(RunEvent.run_id == run_id)
            .order_by(RunEvent.sequence_no)
        )
        return list(result.scalars().all())

    async def generate_run_log_hash(self, run_id: int) -> str:
        """Generate deterministic hash from evidence-boundary events.

        Excludes: onchain_finalize events AND error events with
        onchain_finalize_failed=True (both are post-chain operational).
        """
        events = await self._get_ordered_events(run_id)
        evidence_events = [
            event_to_canonical_dict(e) for e in events
            if is_evidence_event_type(e.event_type) and not _is_post_chain_error(e)
        ]
        return compute_evidence_hash(evidence_events)

    async def create_audit_trail(self, run: Run) -> list[VerificationArtifact]:
        """Create verification artifacts for a finalized run."""
        events = await self._get_ordered_events(run.run_id)
        artifacts: list[VerificationArtifact] = []

        # 1. challenge_config — fail closed if missing
        challenge = await self.db.get(Challenge, run.challenge_id)
        if not challenge:
            raise ValueError(f"Challenge {run.challenge_id} not found — cannot create audit trail")
        config_hash = hashlib.sha256(
            (challenge.config_json or "").encode()
        ).hexdigest()
        artifacts.append(VerificationArtifact(
            run_id=run.run_id,
            artifact_type="challenge_config",
            uri_or_ref=f"challenge:{run.challenge_id}",
            content_hash=config_hash,
        ))

        # 2. submission_hash — fail closed if missing
        agent = await self.db.get(Agent, run.agent_id)
        if not agent:
            raise ValueError(f"Agent {run.agent_id} not found — cannot create audit trail")
        artifacts.append(VerificationArtifact(
            run_id=run.run_id,
            artifact_type="submission_hash",
            uri_or_ref=f"agent:{run.agent_id}",
            content_hash=agent.submission_hash,
        ))

        # 3. quote_set
        quote_refs = [
            e.quote_snapshot_ref for e in events
            if e.quote_snapshot_ref
        ]
        quote_set_data = _canonical_serialize(quote_refs)
        artifacts.append(VerificationArtifact(
            run_id=run.run_id,
            artifact_type="quote_set",
            uri_or_ref=quote_set_data,
            content_hash=hashlib.sha256(quote_set_data.encode()).hexdigest(),
        ))

        # 4. tx_receipt
        tx_sigs = [e.tx_signature for e in events if e.tx_signature]
        tx_data = _canonical_serialize(tx_sigs)
        artifacts.append(VerificationArtifact(
            run_id=run.run_id,
            artifact_type="tx_receipt",
            uri_or_ref=tx_data,
            content_hash=hashlib.sha256(tx_data.encode()).hexdigest(),
        ))

        # 5. audit_log_hash — recompute and verify against stored hash
        recomputed_hash = await self.generate_run_log_hash(run.run_id)
        stored_hash = run.run_log_hash or ""
        if recomputed_hash != stored_hash:
            raise ValueError(
                f"Run {run.run_id} hash mismatch: stored={stored_hash[:16]}... "
                f"recomputed={recomputed_hash[:16]}..."
            )
        artifacts.append(VerificationArtifact(
            run_id=run.run_id,
            artifact_type="audit_log_hash",
            uri_or_ref=f"run:{run.run_id}",
            content_hash=run.run_log_hash or "",
        ))

        for a in artifacts:
            self.db.add(a)
        await self.db.flush()

        return artifacts

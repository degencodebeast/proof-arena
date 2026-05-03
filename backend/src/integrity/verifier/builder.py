"""Public Verifier V0 — pure compose over Cat module + targeted reads."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import AgentTemplate, RunEvent, VerificationArtifact
from src.integrity.cats.wallet_safety import (
    compute_wallet_safety_cat,
    resolve_run_and_instance,
)
from src.integrity.verifier.schemas import (
    VerifierCatsBlock,
    VerifierEvidenceBlock,
    VerifierLineageBlock,
    VerifierRunBlock,
    VerifierRunResponse,
    VerifierTemplateBlock,
    VerifierVerificationArtifactEntry,
)


async def build_verifier_run_response(
    db: AsyncSession, run_id: int,
) -> VerifierRunResponse:
    """Compose the Verifier V0 response. Read-only.

    Calls resolve_run_and_instance for resolver gating (raises domain
    exceptions on failure), compute_wallet_safety_cat for the Cat verdict
    (verbatim — no Cat-logic duplicated here), plus targeted reads for
    evidence/lineage/template. No DB writes.
    """
    run, agent, instance = await resolve_run_and_instance(db, run_id)
    cat_response = await compute_wallet_safety_cat(db, run_id)
    template = await db.get(AgentTemplate, instance.template_id)

    artifact_rows = (
        await db.execute(
            select(VerificationArtifact)
            .where(VerificationArtifact.run_id == run_id)
            .order_by(VerificationArtifact.artifact_id)
        )
    ).scalars().all()
    artifact_entries = [
        VerifierVerificationArtifactEntry(
            artifact_id=a.artifact_id,
            artifact_type=a.artifact_type,
            content_hash=a.content_hash,
            created_at=a.created_at,
        )
        for a in artifact_rows
    ]

    event_count = (
        await db.execute(
            select(func.count())
            .select_from(RunEvent)
            .where(RunEvent.run_id == run_id)
        )
    ).scalar_one()

    last_event = (
        await db.execute(
            select(RunEvent.sequence_no, RunEvent.event_type)
            .where(RunEvent.run_id == run_id)
            .order_by(RunEvent.sequence_no.desc())
            .limit(1)
        )
    ).first()
    last_event_sequence_no = last_event.sequence_no if last_event else None
    last_event_type = last_event.event_type if last_event else None

    return VerifierRunResponse(
        run=VerifierRunBlock(
            run_id=run.run_id,
            challenge_id=run.challenge_id,
            status=run.status,
            completion_status=run.completion_status,
            invalid_reason=run.invalid_reason,
            provider_type=run.provider_type,
            starting_value=run.starting_value,
            ending_value=run.ending_value,
            iterations_used=run.iterations_used,
            run_log_hash=run.run_log_hash,
            started_at=run.started_at,
            ended_at=run.ended_at,
            created_at=run.created_at,
            app_version=run.app_version,
            challenge_type=run.challenge_type,
            challenge_version=run.challenge_version,
            action_schema_version=run.action_schema_version,
            evidence_schema_version=run.evidence_schema_version,
        ),
        lineage=VerifierLineageBlock(
            instance_id=instance.instance_id,
            trust_label=instance.trust_label,
            subject_type=agent.subject_type,
            template=VerifierTemplateBlock(
                template_key=template.template_key,
                template_version=template.template_version,
                template_version_at_deploy=instance.template_version_at_deploy,
                description=template.description,
                is_deployable=bool(template.is_deployable),
            ),
        ),
        evidence=VerifierEvidenceBlock(
            run_log_hash=run.run_log_hash,
            run_event_count=event_count,
            last_event_sequence_no=last_event_sequence_no,
            last_event_type=last_event_type,
            verification_artifacts=artifact_entries,
        ),
        cats=VerifierCatsBlock(wallet_safety=cat_response),
    )

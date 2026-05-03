"""Public Verifier V0 — pure compose over Cat module + targeted reads.

Composes:
- resolve_run_and_instance from src.integrity.cats.wallet_safety (resolver/gates)
- compute_wallet_safety_cat from src.integrity.cats.wallet_safety (Cat verdict)
- VerificationArtifact metadata-only reads (no uri_or_ref leakage)
- RunEvent aggregate signals (count, last sequence_no, last event_type)
- AgentTemplate lineage row

Read-only. No DB writes. No Cat-verdict logic duplicated here.
"""
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession

from src.integrity.verifier.schemas import VerifierRunResponse


async def build_verifier_run_response(
    db: AsyncSession, run_id: int,
) -> VerifierRunResponse:
    raise NotImplementedError("Filled in by Task 5.")

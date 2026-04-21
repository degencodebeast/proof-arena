"""Public read-only endpoint exposing the V2 failure taxonomy copy map.

Returns a stable JSON shape keyed by enum ``.value``; frontend maps those
keys directly off ``runs.invalid_reason`` and
``agent_instances.last_failure_reason`` without any translation. No auth is
required — the taxonomy is public product copy, not operational data.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from src.integrity.failure_taxonomy import RunInvalidReason, SagaFailureReason
from src.integrity.failure_taxonomy_copy import FAILURE_COPY_MAP

router = APIRouter()


class FailureReasonCopy(BaseModel):
    title: str
    description: str


class FailureTaxonomyResponse(BaseModel):
    saga_failure_reasons: dict[str, FailureReasonCopy]
    run_invalid_reasons: dict[str, FailureReasonCopy]


def _render() -> FailureTaxonomyResponse:
    return FailureTaxonomyResponse(
        saga_failure_reasons={
            reason.value: FailureReasonCopy(**FAILURE_COPY_MAP[reason])
            for reason in SagaFailureReason
        },
        run_invalid_reasons={
            reason.value: FailureReasonCopy(**FAILURE_COPY_MAP[reason])
            for reason in RunInvalidReason
        },
    )


@router.get("/failure-taxonomy", response_model=FailureTaxonomyResponse)
async def get_failure_taxonomy() -> FailureTaxonomyResponse:
    """Return human-readable copy for every V2 failure reason.

    Public — the frontend fetches this once at load and caches client-side.
    """

    return _render()

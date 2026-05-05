# tests/integration/test_rebalance_evidence_summary_schema.py
"""Defect 3 (MEDIUM) regression test — canonical summary schema lock.

Verifies that the summary field in the artifact payload contains exactly the
4 keys required by spec §5.5 line 198:
  - drift_bps_pre_run
  - drift_bps_post_run
  - total_traded_value_base_units  (was total_value_base_units — renamed)
  - max_leg_slippage_bps           (new field)

The old emission had:
  - drift_bps_pre_run    ✓
  - drift_bps_post_run   ✓
  - total_value_base_units  ✗ (wrong name)
  - (missing max_leg_slippage_bps)

This test FAILS before Fix 3.
It PASSES after Fix 3.
"""
from __future__ import annotations

import json
import pytest
from sqlalchemy import select

from src.db.models import VerificationArtifact
from src.challenges.rebalance_execution import RebalanceExecutionChallenge
from tests._rebalance_helpers import (
    make_rebalance_envelope,
    make_completed_rebalance_run,
    make_rebalance_instance,
)

_REQUIRED_SUMMARY_KEYS = frozenset({
    "drift_bps_pre_run",
    "drift_bps_post_run",
    "total_traded_value_base_units",
    "max_leg_slippage_bps",
})


@pytest.mark.asyncio
async def test_summary_has_exactly_spec_required_keys(db):
    """summary must contain exactly 4 spec-required keys (exact set equality).

    Negative lock: total_value_base_units must NOT appear.
    All values must be integers.
    """
    template, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=False,
    )

    cfg = make_rebalance_envelope()
    cfg["starting_usdc"] = 100_000_000
    adapter = RebalanceExecutionChallenge(cfg)
    await adapter.emit_run_evidence(db, run, events=[])

    artifact = (
        await db.execute(
            select(VerificationArtifact).where(
                VerificationArtifact.run_id == run.run_id,
                VerificationArtifact.artifact_type == "rebalance_evidence_v1",
            )
        )
    ).scalar_one()

    payload = json.loads(artifact.uri_or_ref)
    summary = payload["summary"]

    # Exact key-set equality per spec §5.5
    assert set(summary.keys()) == _REQUIRED_SUMMARY_KEYS, (
        f"summary keys mismatch.\n"
        f"  Expected: {sorted(_REQUIRED_SUMMARY_KEYS)}\n"
        f"  Got:      {sorted(summary.keys())}\n"
        f"  Missing:  {sorted(_REQUIRED_SUMMARY_KEYS - set(summary.keys()))}\n"
        f"  Extra:    {sorted(set(summary.keys()) - _REQUIRED_SUMMARY_KEYS)}"
    )

    # Negative lock: the old misspelled key must not exist
    assert "total_value_base_units" not in summary, (
        "'total_value_base_units' found in summary — must be renamed to "
        "'total_traded_value_base_units' per spec §5.5 line 198."
    )

    # All values must be integers (V0: drift stays same, traded=sum(legs), slippage=0)
    for key, val in summary.items():
        assert isinstance(val, int), (
            f"summary[{key!r}] = {val!r} (type {type(val).__name__}), expected int"
        )

"""Smoke seed script tests.

The live Docker smoke needs a deterministic completed hosted-instance run
without invoking Solana, Privy, AgentOS, or the full demo lifecycle.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_seed_v2_1_smoke_run_creates_cat_and_verifier_readable_run(db):
    from scripts.seed_v2_1_smoke_run import seed_v2_1_smoke_run
    from src.integrity.cats.wallet_safety import compute_wallet_safety_cat
    from src.integrity.verifier.builder import build_verifier_run_response

    seeded = await seed_v2_1_smoke_run(db)

    cat = await compute_wallet_safety_cat(db, seeded.run_id)
    verifier = await build_verifier_run_response(db, seeded.run_id)

    assert cat.result == "pass"
    assert cat.trust_label == "benchmarked_canonical_template"
    assert cat.run_completion_status == "complete"
    assert verifier.verifier_version == "v0"
    assert verifier.run.run_id == seeded.run_id
    assert verifier.lineage.trust_label == "benchmarked_canonical_template"
    assert verifier.evidence.run_event_count == 2
    assert verifier.evidence.last_event_type == "finalize"
    assert len(verifier.evidence.verification_artifacts) == 1
    assert verifier.cats.wallet_safety == cat

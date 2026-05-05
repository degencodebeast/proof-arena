"""Verifier + Rebalance Policy Cat — integration tests (Task 23).

Covers spec §10 tests 8 + 9:
  - cats.rebalance_policy is verbatim compute_rebalance_policy_cat for rebalance runs
  - cats.wallet_safety is unaffected (regression-lock)
  - cats.rebalance_policy is None for non-rebalance (swap) runs
  - no uri_or_ref or private-field leakage in Verifier response
  - existing v0 wallet-safety verifier flow still works on a swap run (regression)
"""
from __future__ import annotations

import json
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_db
from src.main import app
from src.integrity.cats.wallet_safety import compute_wallet_safety_cat
from src.integrity.cats.rebalance_policy import compute_rebalance_policy_cat
from tests._rebalance_helpers import (
    assert_no_private_field_leakage,
    make_completed_rebalance_run,
    make_completed_swap_run,
    make_rebalance_instance,
    make_swap_instance,
)

pytestmark = pytest.mark.integration


class _FakeUser:
    def __init__(self, privy_user_id: str):
        self.privy_user_id = privy_user_id


@pytest_asyncio.fixture
async def http_client(db: AsyncSession):
    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 1 — cats.rebalance_policy verbatim for rebalance_executor_v1 runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verifier_embeds_rebalance_policy_verbatim(db, http_client, monkeypatch):
    """cats.rebalance_policy must deep-equal compute_rebalance_policy_cat output.

    Locks the no-duplication discipline — Verifier composes; never recomputes.
    """
    _tmpl, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
        evidence_overrides={"legs": []},
    )
    await db.commit()

    # Auth: rebalance instance uses benchmark_compatible_customized_instance trust_label.
    owner_ref = instance.instance_owner_ref

    async def _correct_owner(_creds):
        return _FakeUser(privy_user_id=owner_ref)

    monkeypatch.setattr("src.api.verifier.get_current_user", _correct_owner)

    resp = await http_client.get(
        f"/api/v1/verifier/runs/{run.run_id}",
        headers={"Authorization": "Bearer fake-token"},
    )
    assert resp.status_code == 200, resp.text

    expected = await compute_rebalance_policy_cat(db, run.run_id)
    assert resp.json()["cats"]["rebalance_policy"] == expected.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Test 2 — cats.wallet_safety unchanged on rebalance run (regression-lock)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verifier_wallet_safety_still_populated(db, http_client, monkeypatch):
    """cats.wallet_safety must still equal compute_wallet_safety_cat verbatim on a rebalance run.

    Ensures Task 23 changes do not alter the existing wallet_safety embed.
    """
    _tmpl, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
        evidence_overrides={"legs": []},
    )
    await db.commit()

    owner_ref = instance.instance_owner_ref

    async def _correct_owner(_creds):
        return _FakeUser(privy_user_id=owner_ref)

    monkeypatch.setattr("src.api.verifier.get_current_user", _correct_owner)

    resp = await http_client.get(
        f"/api/v1/verifier/runs/{run.run_id}",
        headers={"Authorization": "Bearer fake-token"},
    )
    assert resp.status_code == 200, resp.text

    expected_ws = await compute_wallet_safety_cat(db, run.run_id)
    assert resp.json()["cats"]["wallet_safety"] == expected_ws.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Test 3 — cats.rebalance_policy is None for swap (non-rebalance) runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verifier_cats_rebalance_policy_null_for_swap_runs(db, http_client, monkeypatch):
    """Swap run → cats.rebalance_policy must be None; cats.wallet_safety must be present."""
    _tmpl, instance, agent = await make_swap_instance(db)
    run = await make_completed_swap_run(db, agent=agent, instance=instance)
    await db.commit()

    owner_ref = instance.instance_owner_ref

    async def _correct_owner(_creds):
        return _FakeUser(privy_user_id=owner_ref)

    monkeypatch.setattr("src.api.verifier.get_current_user", _correct_owner)

    resp = await http_client.get(
        f"/api/v1/verifier/runs/{run.run_id}",
        headers={"Authorization": "Bearer fake-token"},
    )
    assert resp.status_code == 200, resp.text

    cats = resp.json()["cats"]
    assert cats["rebalance_policy"] is None
    assert cats["wallet_safety"] is not None


# ---------------------------------------------------------------------------
# Test 4 — no uri_or_ref or private field leakage in full Verifier response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verifier_does_not_leak_uri_or_ref_or_private_fields(
    db, http_client, monkeypatch,
):
    """Full Verifier response for a rebalance run must pass assert_no_private_field_leakage."""
    _tmpl, instance, agent = await make_rebalance_instance(db)
    run = await make_completed_rebalance_run(
        db, agent=agent, instance=instance, with_evidence=True,
        evidence_overrides={"legs": []},
    )
    await db.commit()

    owner_ref = instance.instance_owner_ref

    async def _correct_owner(_creds):
        return _FakeUser(privy_user_id=owner_ref)

    monkeypatch.setattr("src.api.verifier.get_current_user", _correct_owner)

    resp = await http_client.get(
        f"/api/v1/verifier/runs/{run.run_id}",
        headers={"Authorization": "Bearer fake-token"},
    )
    assert resp.status_code == 200, resp.text

    assert_no_private_field_leakage(
        resp.json(),
        fixture_values=["<test-wallet-rebalance>", "<test-priv-id-rebalance>"],
    )


# ---------------------------------------------------------------------------
# Test 5 — regression: existing v0 wallet-safety verifier flow on a swap run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verifier_v0_existing_wallet_safety_flow_unchanged_for_swap_run(
    db, http_client, monkeypatch,
):
    """Regression-lock: the existing v0 verifier flow for swap runs is unchanged.

    Verifies:
    - Response shape includes run / lineage / evidence / cats blocks.
    - cats.wallet_safety equals compute_wallet_safety_cat verbatim.
    - cats.rebalance_policy is absent / null (not introduced for swap runs).
    - verifier_version is still "v0".
    """
    _tmpl, instance, agent = await make_swap_instance(db)
    run = await make_completed_swap_run(db, agent=agent, instance=instance)
    await db.commit()

    owner_ref = instance.instance_owner_ref

    async def _correct_owner(_creds):
        return _FakeUser(privy_user_id=owner_ref)

    monkeypatch.setattr("src.api.verifier.get_current_user", _correct_owner)

    resp = await http_client.get(
        f"/api/v1/verifier/runs/{run.run_id}",
        headers={"Authorization": "Bearer fake-token"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Shape invariants.
    assert body["verifier_version"] == "v0"
    assert "run" in body
    assert "lineage" in body
    assert "evidence" in body
    assert "cats" in body

    # wallet_safety verbatim embed (unchanged by Task 23).
    expected_ws = await compute_wallet_safety_cat(db, run.run_id)
    assert body["cats"]["wallet_safety"] == expected_ws.model_dump(mode="json")

    # rebalance_policy null for swap run.
    assert body["cats"].get("rebalance_policy") is None

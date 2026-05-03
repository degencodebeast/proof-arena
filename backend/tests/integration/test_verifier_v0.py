"""Public Verifier V0 — 19 acceptance tests for GET /api/v1/verifier/runs/{run_id}.

Helpers (_seed_template, _seed_instance, _seed_bridge_agent, _seed_run, http_client)
are duplicated from tests/integration/test_wallet_safety_cat.py intentionally,
to keep the Verifier and Cat test files independently audit-able. If the helpers
diverge later, that is a deliberate signal to revisit factoring into a shared
module — not now.
"""
from __future__ import annotations

import json
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_db
from src.db.models import Agent, AgentInstance, AgentTemplate, Run
from src.main import app


_ENV = json.dumps({
    "allowed_token_universe": ["SOL", "devUSDC"],
    "max_slippage_bps": 50,
    "max_position_size": 1_000_000,
    "max_iterations": 8,
    "max_runtime_seconds": 180,
})


async def _seed_template(db: AsyncSession) -> int:
    template = AgentTemplate(
        template_key="swap_executor_v1",
        template_version="1",
        description="Canonical swap executor template",
        allowed_fields_json=_ENV,
        default_config_json=_ENV,
        system_prompt="balanced",  # AgentTemplate.system_prompt is non-nullable.
        is_deployable=True,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template.template_id


async def _seed_instance(
    db: AsyncSession,
    *,
    template_id: int,
    trust_label: str = "benchmark_compatible_customized_instance",
    instance_owner_ref: str = "owner-1",
    status: str = "live",
) -> AgentInstance:
    instance = AgentInstance(
        template_id=template_id,
        template_version_at_deploy="1",
        instance_owner_ref=instance_owner_ref,
        effective_config_json=_ENV,
        runtime_handle_json=json.dumps({"handle": "fake"}),
        wallet_address="SoLAddrxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        hosted_wallet_ref="hw-1",
        wallet_provider="privy",
        trust_label=trust_label,
        status=status,
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return instance


async def _seed_bridge_agent(
    db: AsyncSession,
    *,
    instance_id: int,
    subject_type: str = "customized_instance",
    use_metadata_ref: bool = True,
    privy_user_id_override: str | None = None,
    metadata_ref_override: str | None = None,
) -> Agent:
    agent = Agent(
        subject_type=subject_type,
        privy_user_id=(
            privy_user_id_override
            if privy_user_id_override is not None
            else f"instance:{instance_id}"
        ),
        metadata_ref=(
            metadata_ref_override
            if metadata_ref_override is not None
            else (f"agent_instances/{instance_id}" if use_metadata_ref else None)
        ),
        owner_wallet="SoLAgentxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        submission_hash="a" * 64,
        system_prompt="x",          # Agent.system_prompt is non-nullable.
        config_json="{}",           # default exists, set explicitly for determinism.
        display_name="Test Agent",
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


async def _seed_run(
    db: AsyncSession,
    *,
    agent_id: int,
    challenge_id: int = 1,
    completion_status: str | None = "complete",
    invalid_reason: str | None = None,
    provider_type: str = "hosted_instance",
    run_log_hash: str | None = "b" * 64,
) -> Run:
    run = Run(
        challenge_id=challenge_id,
        agent_id=agent_id,
        provider_type=provider_type,
        benchmark_wallet_address="SoLBenchxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        benchmark_wallet_ref="bw-1",
        status="completed",
        completion_status=completion_status,
        invalid_reason=invalid_reason,
        starting_value=1_000_000,
        ending_value=1_001_000,
        iterations_used=4,
        run_log_hash=run_log_hash,
        app_version="1.0.0",
        challenge_type="swap_execution",
        challenge_version="swap_execution_v1",
        action_schema_version="agent_action_v1",
        evidence_schema_version="evidence_v1",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


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
# Acceptance test — Task 2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verifier_v0_returns_404_for_unknown_run_id_via_http(http_client):
    resp = await http_client.get("/api/v1/verifier/runs/999999")
    assert resp.status_code == 404
    assert resp.json() == {"error": "run_not_found"}


@pytest.mark.asyncio
async def test_verifier_v0_returns_404_instance_unresolvable_via_http(
    db, http_client,
):
    """Bridge failure (Agent has no metadata_ref / privy_user_id) → 404 instance_unresolvable."""
    template_id = await _seed_template(db)
    instance = await _seed_instance(db, template_id=template_id)
    agent = await _seed_bridge_agent(
        db,
        instance_id=instance.instance_id,
        use_metadata_ref=False,
        privy_user_id_override="bogus-not-a-bridge",
    )
    run = await _seed_run(db, agent_id=agent.agent_id)
    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 404
    assert resp.json() == {"error": "instance_unresolvable"}


@pytest.mark.asyncio
async def test_verifier_v0_returns_422_for_completion_status_null_via_http(
    db, http_client,
):
    """Run still in progress (completion_status IS NULL) → 422 run_not_final."""
    template_id = await _seed_template(db)
    instance = await _seed_instance(db, template_id=template_id)
    agent = await _seed_bridge_agent(db, instance_id=instance.instance_id)
    run = await _seed_run(
        db, agent_id=agent.agent_id, completion_status=None,
    )
    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "run_not_final"
    assert "lifecycle_status" in body


@pytest.mark.asyncio
async def test_verifier_v0_v1_local_provider_runs_out_of_scope_via_http(
    db, http_client,
):
    """V1 local-provider runs are out of V0 scope → 422 unsupported_provider_type."""
    template_id = await _seed_template(db)
    instance = await _seed_instance(db, template_id=template_id)
    agent = await _seed_bridge_agent(db, instance_id=instance.instance_id)
    run = await _seed_run(
        db, agent_id=agent.agent_id, provider_type="local",
    )
    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 422
    assert resp.json() == {
        "error": "unsupported_provider_type",
        "provider_type": "local",
    }


@pytest.mark.asyncio
async def test_verifier_v0_external_custom_runtime_returns_422_defensively_via_http(
    db, http_client,
):
    """external_custom_runtime is reserved-only in V2; defensive 422."""
    template_id = await _seed_template(db)
    instance = await _seed_instance(
        db, template_id=template_id,
        trust_label="external_custom_runtime",
    )
    agent = await _seed_bridge_agent(db, instance_id=instance.instance_id)
    run = await _seed_run(db, agent_id=agent.agent_id)
    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 422
    assert resp.json() == {
        "error": "unsupported_trust_label",
        "trust_label": "external_custom_runtime",
    }


@pytest.mark.asyncio
async def test_verifier_v0_non_live_instance_returns_404_instance_unresolvable_via_http(
    db, http_client,
):
    """A paused/torn-down instance must collapse to 404 instance_unresolvable.

    Locks the asymmetric-with-trust_label rule (spec §8): trust_label is a
    public contract enum so 422 is fine, but instance.status is operational
    so non-live cases collapse to the bridge-failure 404.
    """
    template_id = await _seed_template(db)
    instance = await _seed_instance(
        db, template_id=template_id, status="paused",
    )
    agent = await _seed_bridge_agent(db, instance_id=instance.instance_id)
    run = await _seed_run(db, agent_id=agent.agent_id)
    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 404
    assert resp.json() == {"error": "instance_unresolvable"}

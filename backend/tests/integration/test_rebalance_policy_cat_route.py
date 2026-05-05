"""Task 22 — Rebalance Policy Cat HTTP route integration tests.

Spec §10 test 10 (error-code parity) — 9 test cases covering:
  404 run_not_found, 422 run_not_final, 422 unsupported_provider_type,
  404 instance_unresolvable, 422 unsupported_template, 422 unsupported_trust_label,
  403 not_instance_owner, 500 internal_error, 200 pass for canonical template.

Test helpers mirror test_wallet_safety_cat.py: same seed shapes, same http_client
pattern (get_db override + ASGITransport + AsyncClient).
"""
from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models import Agent, AgentInstance, AgentTemplate, Run, VerificationArtifact

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Locked effective_config envelope for rebalance_executor_v1 instances
# ---------------------------------------------------------------------------

# V0 rebalance envelope shape (7 fields per spec §5.1 / §5.2). Previously this
# fixture used the swap-shaped envelope, which only worked because the Cat used
# to read its envelope from the artifact's effective_envelope. After the Codex
# Round-2 trust-source fix, the Cat reads json.loads(instance.effective_config_json)
# directly, so the deployed envelope MUST be rebalance-shaped.
_ENV = {
    "allowed_token_universe": [
        "So11111111111111111111111111111111111111112",
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    ],
    "target_allocations": {
        "So11111111111111111111111111111111111111112": 0.5,
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 0.3,
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": 0.2,
    },
    "rebalance_threshold_bps": 50,
    "max_slippage_bps": 100,
    "max_position_weight": 0.7,
    "max_trade_value": 1_000_000_000,
    "dry_run": True,
}


# ---------------------------------------------------------------------------
# Seed helpers — adapted from test_wallet_safety_cat.py
# ---------------------------------------------------------------------------


async def _seed_template(
    db: AsyncSession,
    template_key: str = "rebalance_executor_v1",
) -> int:
    tmpl = AgentTemplate(
        template_key=template_key,
        template_version=template_key,
        description="test",
        allowed_fields_json=json.dumps(sorted(_ENV.keys())),
        default_config_json=json.dumps(_ENV),
        system_prompt="balanced",
        is_deployable=1,
    )
    db.add(tmpl)
    await db.flush()
    return tmpl.template_id


async def _seed_instance(
    db: AsyncSession,
    *,
    template_id: int,
    trust_label: str = "benchmarked_canonical_template",
    instance_owner_ref: str = "owner-1",
    status: str = "live",
) -> AgentInstance:
    inst = AgentInstance(
        template_id=template_id,
        template_version_at_deploy="rebalance_executor_v1",
        instance_owner_ref=instance_owner_ref,
        effective_config_json=json.dumps(_ENV, sort_keys=True),
        wallet_address="sol-addr-rebalance-1",
        hosted_wallet_ref="w-id-rebalance-1",
        wallet_provider="privy",
        status=status,
        trust_label=trust_label,
        runtime_handle_json=json.dumps({"instance_id": "rebalance-executor-v1"}),
    )
    db.add(inst)
    await db.flush()
    return inst


async def _seed_bridge_agent(
    db: AsyncSession,
    *,
    instance_id: int | None,
    subject_type: str = "customized_instance",
    metadata_ref_override: str | None = None,
    privy_user_id_override: str | None = None,
) -> Agent:
    """Synthetic bridge Agent row (mirrors test_wallet_safety_cat.py)."""
    if metadata_ref_override is not None:
        meta = metadata_ref_override
    elif instance_id is not None:
        meta = f"agent_instances/{instance_id}"
    else:
        meta = None
    privy = (
        privy_user_id_override
        if privy_user_id_override is not None
        else (f"instance:{instance_id}" if instance_id is not None else "instance:none")
    )
    agent = Agent(
        privy_user_id=privy,
        owner_wallet="WalletAddr11111111111111111111111111111111",
        display_name=f"rebalance-bridge-{instance_id}",
        submission_hash=hashlib.sha256(
            f"rebalance-{instance_id}".encode()
        ).hexdigest(),
        system_prompt="x",
        config_json="{}",
        status="active",
        moderation_status="active",
        onchain_address="StrategyAddr11111111111111111111111111111111",
        metadata_ref=meta,
        subject_type=subject_type,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _seed_run(
    db: AsyncSession,
    *,
    agent_id: int,
    challenge_id: int = 1,
    completion_status: str | None = "complete",
    provider_type: str = "hosted_instance",
    run_log_hash: str | None = "b" * 64,
) -> Run:
    from datetime import datetime, timezone
    from src.config import settings

    run = Run(
        challenge_id=challenge_id,
        agent_id=agent_id,
        provider_type=provider_type,
        status="completed" if completion_status else "running",
        completion_status=completion_status,
        starting_value=100_000_000,
        ending_value=105_000_000,
        run_log_hash=run_log_hash,
        app_version=settings.APP_VERSION,
        challenge_type="swap_execution",
        challenge_version=settings.CHALLENGE_VERSION,
        action_schema_version=settings.ACTION_SCHEMA_VERSION,
        evidence_schema_version=settings.EVIDENCE_SCHEMA_VERSION,
        ended_at=datetime.now(timezone.utc) if completion_status else None,
    )
    db.add(run)
    await db.flush()
    return run


def _make_valid_evidence_body(*, envelope: dict | None = None) -> str:
    """Return a JSON body that passes all rebalance evidence checks."""
    env = envelope if envelope is not None else {
        **_ENV,
        "rebalance_threshold_bps": 100,
        "max_trade_value": 1_000_000,
        "max_position_weight": 0.9,
        "dry_run": True,
    }
    body = {
        "effective_envelope": env,
        "target_allocations": {"SOL": 0.6, "USDC": 0.4},
        "start_portfolio": {"SOL": 0.5, "USDC": 0.5},
        "prices_used": {"SOL": 150.0, "USDC": 1.0},
        "legs": [],
        "summary": {
            "drift_bps_pre_run": 0,
            "drift_bps_post_run": 0,
        },
    }
    return json.dumps(body)


async def _seed_evidence_artifact(
    db: AsyncSession,
    *,
    run_id: int,
    body: str | None = None,
) -> VerificationArtifact:
    """Seed a valid rebalance_evidence_v1 artifact for the given run."""
    payload = body if body is not None else _make_valid_evidence_body()
    content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    artifact = VerificationArtifact(
        run_id=run_id,
        artifact_type="rebalance_evidence_v1",
        uri_or_ref=payload,
        content_hash=content_hash,
    )
    db.add(artifact)
    await db.flush()
    return artifact


# ---------------------------------------------------------------------------
# http_client fixture — same pattern as test_wallet_safety_cat.py
# ---------------------------------------------------------------------------


@pytest.fixture
async def http_client(db):
    """AsyncClient with get_db overridden to the test session."""
    from httpx import ASGITransport, AsyncClient
    from src.main import app
    from src.db.engine import get_db

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_rebalance_policy_cat_returns_404_for_unknown_run_id(http_client):
    """404 run_not_found: run_id does not exist in the DB."""
    resp = await http_client.get("/api/v1/cats/rebalance_policy/99999")
    assert resp.status_code == 404
    assert resp.json() == {"error": "run_not_found"}


async def test_rebalance_policy_cat_returns_422_run_not_final(db, http_client):
    """422 run_not_final: run has no completion_status (still running)."""
    tid = await _seed_template(db)
    inst = await _seed_instance(db, template_id=tid)
    bridge = await _seed_bridge_agent(db, instance_id=inst.instance_id)
    run = await _seed_run(db, agent_id=bridge.agent_id, completion_status=None)
    await db.commit()

    resp = await http_client.get(f"/api/v1/cats/rebalance_policy/{run.run_id}")
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "run_not_final"
    assert "lifecycle_status" in body


async def test_rebalance_policy_cat_returns_422_unsupported_provider_type(db, http_client):
    """422 unsupported_provider_type: run uses 'local' provider_type."""
    tid = await _seed_template(db)
    inst = await _seed_instance(db, template_id=tid)
    bridge = await _seed_bridge_agent(db, instance_id=inst.instance_id)
    run = await _seed_run(db, agent_id=bridge.agent_id, provider_type="local")
    await db.commit()

    resp = await http_client.get(f"/api/v1/cats/rebalance_policy/{run.run_id}")
    assert resp.status_code == 422
    assert resp.json() == {"error": "unsupported_provider_type", "provider_type": "local"}


async def test_rebalance_policy_cat_returns_404_instance_unresolvable(db, http_client):
    """404 instance_unresolvable: agent.metadata_ref points at non-existent instance_id.

    agent row has metadata_ref pointing to agent_instances/999999 which does not
    exist — resolve_run_and_instance cannot load the instance and raises
    InstanceUnresolvableError.
    """
    tid = await _seed_template(db)
    # Create instance only to get a valid template; then create bridge agent
    # with a metadata_ref pointing to a non-existent instance id.
    bridge = await _seed_bridge_agent(
        db,
        instance_id=None,
        metadata_ref_override="agent_instances/999999",
    )
    run = await _seed_run(db, agent_id=bridge.agent_id)
    await db.commit()

    resp = await http_client.get(f"/api/v1/cats/rebalance_policy/{run.run_id}")
    assert resp.status_code == 404
    assert resp.json() == {"error": "instance_unresolvable"}


async def test_rebalance_policy_cat_returns_422_unsupported_template(db, http_client):
    """422 unsupported_template: instance uses swap_executor_v1, not rebalance_executor_v1."""
    # Use a different template_key — "swap_executor_v1" is NOT the rebalance template.
    tid = await _seed_template(db, template_key="swap_executor_v1")
    inst = await _seed_instance(db, template_id=tid)
    bridge = await _seed_bridge_agent(db, instance_id=inst.instance_id)
    run = await _seed_run(db, agent_id=bridge.agent_id)
    await db.commit()

    resp = await http_client.get(f"/api/v1/cats/rebalance_policy/{run.run_id}")
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "unsupported_template"
    assert body["template_key"] == "swap_executor_v1"


async def test_rebalance_policy_cat_returns_422_unsupported_trust_label(db, http_client):
    """422 unsupported_trust_label: external_custom_runtime reaches resolver and is rejected."""
    tid = await _seed_template(db)
    inst = await _seed_instance(
        db, template_id=tid, trust_label="external_custom_runtime"
    )
    bridge = await _seed_bridge_agent(db, instance_id=inst.instance_id)
    run = await _seed_run(db, agent_id=bridge.agent_id)
    await db.commit()

    resp = await http_client.get(f"/api/v1/cats/rebalance_policy/{run.run_id}")
    assert resp.status_code == 422
    assert resp.json() == {
        "error": "unsupported_trust_label",
        "trust_label": "external_custom_runtime",
    }


async def test_rebalance_policy_cat_returns_403_not_instance_owner(db, http_client):
    """403 not_instance_owner: benchmark_compatible_customized_instance + wrong bearer."""
    from fastapi.security import HTTPAuthorizationCredentials
    from src.auth import get_current_user

    tid = await _seed_template(db)
    owner_token = "rebalance-owner-secret"
    owner_creds = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=owner_token
    )
    owner_user = await get_current_user(owner_creds)
    owner_ref = owner_user.privy_user_id

    inst = await _seed_instance(
        db,
        template_id=tid,
        trust_label="benchmark_compatible_customized_instance",
        instance_owner_ref=owner_ref,
    )
    bridge = await _seed_bridge_agent(db, instance_id=inst.instance_id)
    run = await _seed_run(db, agent_id=bridge.agent_id)
    await db.commit()

    # No auth → 401
    r1 = await http_client.get(f"/api/v1/cats/rebalance_policy/{run.run_id}")
    assert r1.status_code == 401, r1.text

    # Wrong owner → 403
    r2 = await http_client.get(
        f"/api/v1/cats/rebalance_policy/{run.run_id}",
        headers={"Authorization": "Bearer not-the-owner"},
    )
    assert r2.status_code == 403
    assert r2.json() == {"error": "not_instance_owner"}


async def test_rebalance_policy_cat_returns_500_on_unexpected_exception(
    db, http_client, monkeypatch
):
    """500 internal_error: unexpected exception inside compute is caught and locked."""
    tid = await _seed_template(db)
    inst = await _seed_instance(db, template_id=tid)
    bridge = await _seed_bridge_agent(db, instance_id=inst.instance_id)
    run = await _seed_run(db, agent_id=bridge.agent_id)
    await db.commit()

    async def _boom(_db, _run_id):  # pragma: no cover — invoked via monkeypatch only
        raise RuntimeError("synthetic rebalance compute failure with sensitive details")

    monkeypatch.setattr("src.api.cats.compute_rebalance_policy_cat", _boom)

    resp = await http_client.get(f"/api/v1/cats/rebalance_policy/{run.run_id}")
    assert resp.status_code == 500
    assert resp.json() == {"error": "internal_error"}
    assert "synthetic rebalance compute failure" not in resp.text
    assert "sensitive details" not in resp.text


async def test_rebalance_policy_cat_returns_200_for_canonical_template_with_evidence(
    db, http_client
):
    """200 pass: canonical template + valid evidence artifact → Cat result returned."""
    tid = await _seed_template(db)
    inst = await _seed_instance(
        db, template_id=tid, trust_label="benchmarked_canonical_template"
    )
    bridge = await _seed_bridge_agent(db, instance_id=inst.instance_id)
    run = await _seed_run(db, agent_id=bridge.agent_id)
    await _seed_evidence_artifact(db, run_id=run.run_id)
    await db.commit()

    resp = await http_client.get(f"/api/v1/cats/rebalance_policy/{run.run_id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["trust_label"] == "benchmarked_canonical_template"
    assert "result" in data
    assert "checks" in data

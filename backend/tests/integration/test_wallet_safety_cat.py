"""Wallet Safety Cat — integration tests.

Reuses the existing async conftest at tests/integration/conftest.py for the
`db` AsyncSession fixture. These local helpers wrap that fixture's primitives
to add the bridge fields (`metadata_ref`, `subject_type`, `provider_type`)
that the conftest factories don't accept.
"""
import json
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models import Agent, AgentInstance, AgentTemplate, Run, RunEvent

pytestmark = pytest.mark.integration

# Locked five-field envelope for AgentInstance.effective_config_json
_ENV = {
    "max_slippage_bps": 100,
    "max_position_size": 10_000_000,
    "allowed_token_universe": ["SOL", "USDC"],
    "max_runtime_seconds": 300,
    "max_iterations": 20,
}


async def _seed_template(db: AsyncSession) -> int:
    tmpl = AgentTemplate(
        template_key="swap_executor_v1",
        template_version="swap_executor_v1",
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
    trust_label: str = "benchmark_compatible_customized_instance",
    instance_owner_ref: str = "owner-1",
    status: str = "live",
) -> AgentInstance:
    inst = AgentInstance(
        template_id=template_id,
        template_version_at_deploy="swap_executor_v1",
        instance_owner_ref=instance_owner_ref,
        effective_config_json=json.dumps(_ENV, sort_keys=True),
        wallet_address="sol-addr-1",
        hosted_wallet_ref="w-id-1",
        wallet_provider="privy",
        status=status,
        trust_label=trust_label,
        runtime_handle_json=json.dumps({"instance_id": "swap-executor-v1"}),
    )
    db.add(inst)
    await db.flush()
    return inst


async def _seed_bridge_agent(
    db: AsyncSession,
    *,
    instance_id: int | None,
    subject_type: str = "customized_instance",
    use_metadata_ref: bool = True,
    privy_user_id_override: str | None = None,
    metadata_ref_override: str | None = None,
) -> Agent:
    """Synthetic-Agent bridge row created the way challenge_service.create_run_for_instance does it."""
    import hashlib
    if metadata_ref_override is not None:
        meta = metadata_ref_override
    elif use_metadata_ref and instance_id is not None:
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
        display_name=f"bridge-{instance_id}",
        submission_hash=hashlib.sha256(b"x").hexdigest(),
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
    invalid_reason: str | None = None,
    provider_type: str = "hosted_instance",
    run_log_hash: str | None = "a" * 64,
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
        invalid_reason=invalid_reason,
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


# =====================================================================
# Task 2 — 404 run_not_found for unknown run_id
# =====================================================================


async def test_wallet_safety_cat_returns_404_for_unknown_run_id(db):
    from src.integrity.cats.wallet_safety import (
        compute_wallet_safety_cat, RunNotFoundError,
    )
    with pytest.raises(RunNotFoundError):
        await compute_wallet_safety_cat(db, 99999)


# =====================================================================
# Task 3 — 422 run_not_final when Run.completion_status IS NULL
# =====================================================================


async def test_wallet_safety_cat_returns_422_for_completion_status_null(db):
    from src.integrity.cats.wallet_safety import (
        compute_wallet_safety_cat, RunNotFinalError,
    )
    tid = await _seed_template(db)
    inst = await _seed_instance(db, template_id=tid)
    bridge = await _seed_bridge_agent(db, instance_id=inst.instance_id)
    run = await _seed_run(db, agent_id=bridge.agent_id, completion_status=None)
    await db.commit()

    with pytest.raises(RunNotFinalError) as ei:
        await compute_wallet_safety_cat(db, run.run_id)
    # Must surface the lifecycle status (reference-only) in the error.
    assert ei.value.lifecycle_status == "running"


# =====================================================================
# Task 4 — 422 unsupported_provider_type for V1 local runs
# =====================================================================


async def test_wallet_safety_cat_v1_local_provider_runs_out_of_scope(db):
    from src.integrity.cats.wallet_safety import (
        compute_wallet_safety_cat, UnsupportedProviderTypeError,
    )
    tid = await _seed_template(db)
    inst = await _seed_instance(db, template_id=tid)
    bridge = await _seed_bridge_agent(db, instance_id=inst.instance_id)
    run = await _seed_run(db, agent_id=bridge.agent_id, provider_type="local")
    await db.commit()

    with pytest.raises(UnsupportedProviderTypeError) as ei:
        await compute_wallet_safety_cat(db, run.run_id)
    assert ei.value.provider_type == "local"


# =====================================================================
# Task 5 — Synthetic-Agent bridge resolver + 404 instance_unresolvable
# =====================================================================


@pytest.mark.parametrize(
    "mode,metadata_ref_override,privy_user_id_override",
    [
        ("malformed_metadata_no_fallback",      "garbage://no-instance",     "not-instance-prefixed"),
        ("metadata_points_to_missing_instance", "agent_instances/99999",     "instance:99999"),
        ("privy_fallback_only_but_missing",     None,                        "instance:99999"),
        ("metadata_and_fallback_both_garbage",  "garbage",                   "garbage"),
    ],
)
async def test_wallet_safety_cat_returns_404_instance_unresolvable_for_unresolvable_bridge(
    db, mode, metadata_ref_override, privy_user_id_override,
):
    from src.integrity.cats.wallet_safety import (
        compute_wallet_safety_cat, InstanceUnresolvableError,
    )
    bridge = await _seed_bridge_agent(
        db,
        instance_id=None,
        metadata_ref_override=metadata_ref_override,
        privy_user_id_override=privy_user_id_override,
    )
    run = await _seed_run(db, agent_id=bridge.agent_id)
    await db.commit()

    with pytest.raises(InstanceUnresolvableError):
        await compute_wallet_safety_cat(db, run.run_id)


# =====================================================================
# Task 6 — Defensive 422 unsupported_trust_label for external_custom_runtime
# =====================================================================


async def test_wallet_safety_cat_external_custom_runtime_returns_422_defensively(db):
    from src.integrity.cats.wallet_safety import (
        compute_wallet_safety_cat, UnsupportedTrustLabelError,
    )
    tid = await _seed_template(db)
    inst = await _seed_instance(db, template_id=tid, trust_label="external_custom_runtime")
    bridge = await _seed_bridge_agent(db, instance_id=inst.instance_id)
    run = await _seed_run(db, agent_id=bridge.agent_id)
    await db.commit()

    with pytest.raises(UnsupportedTrustLabelError) as ei:
        await compute_wallet_safety_cat(db, run.run_id)
    assert ei.value.trust_label == "external_custom_runtime"


# =====================================================================
# Task 7 — Pass verdict when run is complete and no invalid_reason
# =====================================================================


async def test_wallet_safety_cat_pass_when_run_complete_no_invalid_reason(db):
    from src.integrity.cats.wallet_safety import compute_wallet_safety_cat
    tid = await _seed_template(db)
    inst = await _seed_instance(db, template_id=tid, trust_label="benchmark_compatible_customized_instance")
    bridge = await _seed_bridge_agent(db, instance_id=inst.instance_id)
    run = await _seed_run(db, agent_id=bridge.agent_id, completion_status="complete", invalid_reason=None)
    await db.commit()

    resp = await compute_wallet_safety_cat(db, run.run_id)
    assert resp.result == "pass"
    assert resp.reason is None
    assert resp.critique == ""
    assert resp.run_completion_status == "complete"
    assert resp.off_scope_invalid_reason is None
    assert resp.scope_note is None
    assert resp.run_id == run.run_id
    assert resp.instance_id == inst.instance_id
    assert resp.subject_type == "customized_instance"  # from Agent.subject_type
    assert resp.trust_label == "benchmark_compatible_customized_instance"
    assert all(c.result == "pass" for c in resp.checks)
    assert len(resp.checks) == 10


# =====================================================================
# Task 8 — Fail verdicts for the five wallet-safety RunInvalidReason members
# =====================================================================


@pytest.mark.parametrize(
    "reason,expected_check_id",
    [
        ("mainnet_guard_triggered",          "mainnet_guard_check"),
        ("wallet_policy_rejected",           "wallet_policy_check"),
        ("authorization_signature_rejected", "authorization_signature_check"),
        ("hosted_wallet_unavailable",        "hosted_wallet_available_check"),
        ("invalid_action_attempts_exceeded", "invalid_action_attempts_check"),
    ],
)
async def test_wallet_safety_cat_fails_on_wallet_safety_reasons(db, reason, expected_check_id):
    from src.integrity.cats.wallet_safety import compute_wallet_safety_cat
    tid = await _seed_template(db)
    inst = await _seed_instance(db, template_id=tid)
    bridge = await _seed_bridge_agent(db, instance_id=inst.instance_id)
    run = await _seed_run(
        db, agent_id=bridge.agent_id,
        completion_status="invalid", invalid_reason=reason,
    )
    await db.commit()

    resp = await compute_wallet_safety_cat(db, run.run_id)
    assert resp.result == "fail"
    assert resp.reason == reason
    assert resp.run_completion_status == "invalid"
    assert resp.off_scope_invalid_reason is None
    failing = [c for c in resp.checks if c.result == "fail"]
    assert len(failing) == 1
    assert failing[0].check_id == expected_check_id

"""Local test helpers for rebalance executor V0 tests.

These helpers provide:
- Baseline envelope factories (make_rebalance_envelope, make_swap_envelope)
- Canonical evidence JSON/hash helpers
- Evidence payload builder
- Private-field leakage assertion
- Async DB helpers for Tasks 9, 15
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Baseline envelope factories
# ---------------------------------------------------------------------------

def make_rebalance_envelope(**overrides) -> dict[str, Any]:
    """Return the V0 baseline rebalance envelope merged with overrides."""
    base: dict[str, Any] = {
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
    base.update(overrides)
    return base


def make_swap_envelope(**overrides) -> dict[str, Any]:
    """Return the V2 5-field swap envelope baseline.

    Values are chosen to pass validate_spec().
    """
    base: dict[str, Any] = {
        "allowed_token_universe": [
            "So11111111111111111111111111111111111111112",
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        ],
        "max_slippage_bps": 100,
        "max_position_size": 1_000_000,
        "max_iterations": 20,
        "max_runtime_seconds": 300,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Canonical evidence JSON / hash helpers
# ---------------------------------------------------------------------------

def canonical_rebalance_evidence_json(payload: dict) -> tuple[str, str]:
    """Return (canonical_json, sha256_hexdigest) for an evidence payload.

    Uses the same recipe as policy.engine.record_consent:
    json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    then sha256.hexdigest().
    """
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return canonical, digest


# ---------------------------------------------------------------------------
# Evidence payload builder
# ---------------------------------------------------------------------------

_SOL_MINT = "So11111111111111111111111111111111111111112"
_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
_USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

_DEFAULT_PRICES: dict[str, int] = {
    _SOL_MINT: 1_000_000,
    _USDC_MINT: 1_000_000,
    _USDT_MINT: 1_000_000,
}

_DEFAULT_START_PORTFOLIO: dict[str, int] = {
    _SOL_MINT: 500_000,
    _USDC_MINT: 300_000,
    _USDT_MINT: 200_000,
}


def make_rebalance_evidence_payload(
    *,
    run_id: int,
    instance_id: int,
    envelope: dict,
    prices_used: dict[str, int] | None = None,
    start_portfolio: dict[str, int] | None = None,
    end_portfolio: dict[str, int] | None = None,
    legs: list[dict] | None = None,
    summary: dict | None = None,
) -> dict:
    """Build the canonical-shape rebalance_evidence_v1 payload per spec §5.5.

    HAPPY-PATH PRICED FIXTURE for Cat tests. This helper supplies non-null
    1_000_000 base-unit prices when ``prices_used`` is omitted so Cat tests can
    exercise the success branch of ``price_data_present_check`` without wiring
    up a real observe pipeline. Production ``RebalanceExecutionChallenge.
    emit_run_evidence`` does NOT use this fallback — it emits explicit ``None``
    for every missing price per spec §5.5/§5.6, which is what the Cat-layer
    ``price_data_present_check`` (Task 20) fails on.

    Callers needing a missing-price fixture should pass ``prices_used`` with
    explicit ``None`` entries.

    V0-locked defaults:
    - Every leg status="planned", slippage_bps_realized=0
    - Prices = happy-path 1_000_000 base-units when omitted (test-only fixture)
    - end_portfolio == start_portfolio (dry-run, no execution)
    """
    if prices_used is None:
        prices_used = dict(_DEFAULT_PRICES)

    if start_portfolio is None:
        start_portfolio = dict(_DEFAULT_START_PORTFOLIO)

    if end_portfolio is None:
        end_portfolio = dict(start_portfolio)

    if legs is None:
        target_allocs = envelope.get("target_allocations", {})
        legs = [
            {
                "mint": mint,
                "side": "BUY",
                "size_base_units": 0,
                "slippage_bps_realized": 0,
                "status": "planned",
            }
            for mint in target_allocs
        ]

    if summary is None:
        summary = {
            "drift_bps_pre_run": 0,
            "drift_bps_post_run": 0,
            "total_traded_value_base_units": 0,
            "max_leg_slippage_bps": 0,
        }

    return {
        "evidence_schema_version": "rebalance_evidence_v1",
        "run_id": run_id,
        "instance_id": instance_id,
        "template_key": "rebalance_executor_v1",
        "effective_envelope": envelope,
        "target_allocations": envelope.get("target_allocations", {}),
        "prices_used": prices_used,
        "start_portfolio": start_portfolio,
        "end_portfolio": end_portfolio,
        "legs": legs,
        "dry_run": envelope.get("dry_run", True),
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Private-field leakage assertion
# ---------------------------------------------------------------------------

_PRIVATE_FIELD_NAMES = frozenset({
    "uri_or_ref",
    "wallet_address",
    "hosted_wallet_ref",
    "instance_owner_ref",
    "runtime_handle_json",
    "system_prompt",
    "config_json",
})


def assert_no_private_field_leakage(
    serialized_response: dict,
    fixture_values: list[str],
) -> None:
    """Assert that serialized_response does not leak private fields.

    Checks:
    - json.dumps(serialized_response) does NOT contain any of the private field
      name strings as substrings.
    - json.dumps(serialized_response) does NOT contain any of the fixture_values
      strings as substrings.
    """
    dumped = json.dumps(serialized_response)
    for field_name in _PRIVATE_FIELD_NAMES:
        assert field_name not in dumped, (
            f"Private field {field_name!r} leaked in serialized response"
        )
    for value in fixture_values:
        assert value not in dumped, (
            f"Fixture value {value!r} leaked in serialized response"
        )


# ---------------------------------------------------------------------------
# Stub async helpers for later tasks
# ---------------------------------------------------------------------------

async def make_rebalance_instance(
    db,
    *,
    owner_ref: str = "instance:9001",
    trust_label: str = "benchmark_compatible_customized_instance",
    template_key: str = "rebalance_executor_v1",
    effective_config: dict | None = None,
    **kwargs,
):
    """Creates a rebalance AgentTemplate + AgentInstance + bridge Agent in the test DB.

    Returns (template, instance, agent).

    The bridge Agent has:
    - metadata_ref = f"agent_instances/{instance.instance_id}"
    - subject_type = "customized_instance"
    - privy_user_id = owner_ref (fallback bridge key, e.g. "instance:9001")
    """
    from src.db.models import Agent, AgentInstance, AgentTemplate, VerificationArtifact

    if effective_config is None:
        effective_config = dict(make_rebalance_envelope())

    # Insert or reuse template
    from sqlalchemy import select as _select
    existing_tmpl = (
        await db.execute(
            _select(AgentTemplate).where(AgentTemplate.template_key == template_key)
        )
    ).scalar_one_or_none()
    if existing_tmpl is None:
        template = AgentTemplate(
            template_key=template_key,
            template_version=template_key,
            description="Rebalance test template",
            allowed_fields_json=json.dumps(sorted([
                "allowed_token_universe", "target_allocations", "rebalance_threshold_bps",
                "max_slippage_bps", "max_position_weight", "max_trade_value", "dry_run",
            ])),
            default_config_json=json.dumps(effective_config, sort_keys=True),
            system_prompt="Rebalance the portfolio toward target allocations.",
            is_deployable=1,
        )
        db.add(template)
        await db.flush()
    else:
        template = existing_tmpl

    # Stub consent artifact (nullable FK — insert a placeholder)
    consent_artifact = VerificationArtifact(
        run_id=None,
        artifact_type="deploy_consent_v1",
        uri_or_ref="{}",
        content_hash=hashlib.sha256(b"{}").hexdigest(),
    )
    db.add(consent_artifact)
    await db.flush()

    instance = AgentInstance(
        template_id=template.template_id,
        template_version_at_deploy=template_key,
        instance_owner_ref=owner_ref,
        effective_config_json=json.dumps(effective_config, sort_keys=True),
        wallet_address="<test-wallet-rebalance>",
        hosted_wallet_ref="<test-priv-id-rebalance>",
        wallet_provider="privy",
        runtime_handle_json="{}",
        trust_label=trust_label,
        status="live",
        consent_artifact_id=consent_artifact.artifact_id,
    )
    db.add(instance)
    await db.flush()

    sh = hashlib.sha256(
        f"instance:{instance.instance_id}:{json.dumps(effective_config, sort_keys=True)}".encode()
    ).hexdigest()
    agent = Agent(
        privy_user_id=owner_ref,
        owner_wallet="<test-wallet-rebalance>",
        display_name=f"bridge-rebalance-{instance.instance_id}",
        submission_hash=sh,
        system_prompt="Rebalance the portfolio toward target allocations.",
        config_json=json.dumps(effective_config, sort_keys=True),
        status="active",
        moderation_status="active",
        onchain_address="StrategyAddr11111111111111111111111111111111",
        metadata_ref=f"agent_instances/{instance.instance_id}",
        subject_type="customized_instance",
        provider_type="hosted_instance",
        submission_type="hosted_instance",
    )
    db.add(agent)
    await db.flush()

    return template, instance, agent


async def make_completed_rebalance_run(
    db,
    *,
    agent,
    instance,
    completion_status: str = "complete",
    invalid_reason: str | None = None,
    with_evidence: bool = True,
    evidence_overrides: dict | None = None,
    **kwargs,
):
    """Creates a completed rebalance Run + optional evidence artifact.

    Inserts a Challenge row (rebalance_execution type) + a Run in terminal state.
    If with_evidence=True, also writes a rebalance_evidence_v1 VerificationArtifact.
    """
    from src.db.models import Challenge, Run, VerificationArtifact
    from src.config import settings

    challenge = Challenge(
        challenge_type="rebalance_execution",
        challenge_version="rebalance_execution_v1",
        llm_provider="anthropic",
        llm_model="claude-sonnet-4-20250514",
        config_json=json.dumps({
            "starting_usdc": 100_000_000,
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
        }),
        status="active",
        num_contestants=1,
        num_finalized=0,
    )
    db.add(challenge)
    await db.flush()

    run = Run(
        challenge_id=challenge.challenge_id,
        agent_id=agent.agent_id,
        provider_type="hosted_instance",
        status="completed",
        completion_status=completion_status,
        invalid_reason=invalid_reason,
        starting_value=100_000_000,
        ending_value=100_000_000,
        run_log_hash="a" * 64,
        app_version=settings.APP_VERSION,
        challenge_type="rebalance_execution",
        challenge_version="rebalance_execution_v1",
        action_schema_version=settings.ACTION_SCHEMA_VERSION,
        evidence_schema_version=settings.EVIDENCE_SCHEMA_VERSION,
        ended_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.flush()

    if with_evidence:
        payload = make_rebalance_evidence_payload(
            run_id=run.run_id,
            instance_id=instance.instance_id,
            envelope=make_rebalance_envelope(),
        )
        if evidence_overrides:
            payload.update(evidence_overrides)
        canonical_json, content_hash = canonical_rebalance_evidence_json(payload)
        artifact = VerificationArtifact(
            run_id=run.run_id,
            artifact_type="rebalance_evidence_v1",
            uri_or_ref=canonical_json,
            content_hash=content_hash,
        )
        db.add(artifact)
        await db.flush()

    return run


async def make_completed_swap_run(
    db,
    *,
    agent,
    instance,
    completion_status: str = "complete",
    invalid_reason: str | None = None,
    **kwargs,
):
    """Creates a completed swap Run row in the test DB.

    Inserts a Challenge row (swap_execution type) + a Run in terminal state.
    No evidence artifact — swap runs don't emit rebalance_evidence_v1.
    """
    from src.db.models import Challenge, Run
    from src.config import settings

    challenge = Challenge(
        challenge_type="swap_execution",
        challenge_version=settings.CHALLENGE_VERSION,
        llm_provider="anthropic",
        llm_model="claude-sonnet-4-20250514",
        config_json=json.dumps({
            "starting_usdc": 100_000_000,
            "swap_intents": ["SOL"],
            "max_slippage_bps": 100,
            "iteration_budget": 20,
            "time_budget_secs": 300,
        }),
        status="active",
        num_contestants=1,
        num_finalized=0,
    )
    db.add(challenge)
    await db.flush()

    run = Run(
        challenge_id=challenge.challenge_id,
        agent_id=agent.agent_id,
        provider_type="hosted_instance",
        status="completed",
        completion_status=completion_status,
        invalid_reason=invalid_reason,
        starting_value=100_000_000,
        ending_value=105_000_000,
        run_log_hash="b" * 64,
        app_version=settings.APP_VERSION,
        challenge_type="swap_execution",
        challenge_version=settings.CHALLENGE_VERSION,
        action_schema_version=settings.ACTION_SCHEMA_VERSION,
        evidence_schema_version=settings.EVIDENCE_SCHEMA_VERSION,
        ended_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.flush()

    return run


async def make_swap_instance(
    db,
    *,
    owner_ref: str = "instance:9000",
    trust_label: str = "benchmark_compatible_customized_instance",
    **kwargs,
):
    """Creates a swap AgentTemplate + AgentInstance + bridge Agent in the test DB.

    Returns (template, instance, agent).
    """
    from src.db.models import Agent, AgentInstance, AgentTemplate, VerificationArtifact
    from sqlalchemy import select as _select

    swap_config = dict(make_swap_envelope())

    existing_tmpl = (
        await db.execute(
            _select(AgentTemplate).where(AgentTemplate.template_key == "swap_executor_v1")
        )
    ).scalar_one_or_none()
    if existing_tmpl is None:
        template = AgentTemplate(
            template_key="swap_executor_v1",
            template_version="swap_executor_v1",
            description="Swap test template",
            allowed_fields_json=json.dumps(sorted([
                "allowed_token_universe", "max_slippage_bps", "max_position_size",
                "max_iterations", "max_runtime_seconds",
            ])),
            default_config_json=json.dumps(swap_config, sort_keys=True),
            system_prompt="Execute a fixed-basket swap.",
            is_deployable=1,
        )
        db.add(template)
        await db.flush()
    else:
        template = existing_tmpl

    consent_artifact = VerificationArtifact(
        run_id=None,
        artifact_type="deploy_consent_v1",
        uri_or_ref="{}",
        content_hash=hashlib.sha256(b"{}").hexdigest(),
    )
    db.add(consent_artifact)
    await db.flush()

    instance = AgentInstance(
        template_id=template.template_id,
        template_version_at_deploy="swap_executor_v1",
        instance_owner_ref=owner_ref,
        effective_config_json=json.dumps(swap_config, sort_keys=True),
        wallet_address="<test-wallet-swap>",
        hosted_wallet_ref="<test-priv-id-swap>",
        wallet_provider="privy",
        runtime_handle_json="{}",
        trust_label=trust_label,
        status="live",
        consent_artifact_id=consent_artifact.artifact_id,
    )
    db.add(instance)
    await db.flush()

    sh = hashlib.sha256(
        f"instance:{instance.instance_id}:{json.dumps(swap_config, sort_keys=True)}".encode()
    ).hexdigest()
    agent = Agent(
        privy_user_id=owner_ref,
        owner_wallet="<test-wallet-swap>",
        display_name=f"bridge-swap-{instance.instance_id}",
        submission_hash=sh,
        system_prompt="Execute a fixed-basket swap.",
        config_json=json.dumps(swap_config, sort_keys=True),
        status="active",
        moderation_status="active",
        onchain_address="StrategyAddr11111111111111111111111111111111",
        metadata_ref=f"agent_instances/{instance.instance_id}",
        subject_type="customized_instance",
        provider_type="hosted_instance",
        submission_type="hosted_instance",
    )
    db.add(agent)
    await db.flush()

    return template, instance, agent

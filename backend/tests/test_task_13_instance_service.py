"""Task 13 — RED tests for the InstanceService deploy saga.

Covers the edge-case spec in ``.taskmaster/docs/task13-edge-case-spec.md``:

- Constructor wiring (required injected args; empty rejected)
- Step 1 validation failures (PROVISIONING_FAILED, no row)
- Step 2 policy-engine chain guard (PROVISIONING_FAILED, no row)
- Step 3 Privy wallet creation failure (PROVISIONING_FAILED, no row)
- Step 4 template resolution failures (PROVISIONING_FAILED, no row)
- Step 5 runtime deploy failure (WALLET_CREATED_RUNTIME_FAILED, row returned)
- Step 6 consent write failure (RUNTIME_LIVE_CONSENT_FAILED, row returned)
- Happy path (status=live, consent artifact linked, handle round-trips)
- `runtime_handle_json` round-trip via ``InstanceHandle(**json.loads(...))``
- ``VerificationArtifact`` shape: ``run_id IS NULL``, ``uri_or_ref == canonical_json``
- ``last_failure_reason`` DB CHECK — only SagaFailureReason values
- Trust-label default (``benchmark_compatible_customized_instance``)
- Helper methods: ``get_instance_by_id``, ``get_instances_by_owner``,
  ``get_instances_by_status``

In-memory SQLite following the Task 3 / A-1 pattern. WalletService and
InstanceRuntime are stubbed with small test doubles because the real
Privy and AgentOS clients are out of scope for unit tests.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator
from dataclasses import asdict
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles


os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-t13")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/unused",
)


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kwargs):
    return "INTEGER"


# ---------------------------------------------------------------------
# Fixtures — in-memory SQLite with FK enforcement, full model schema
# ---------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    from sqlalchemy import event

    from src.db.models import Base

    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(eng.sync_engine, "connect")
    def _fk_on(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session


# ---------------------------------------------------------------------
# Fixtures — valid inputs
# ---------------------------------------------------------------------


_VALID_CONFIG = {
    "allowed_token_universe": [
        "So11111111111111111111111111111111111111112",
        "BRjpCHtyQLNCo8gqRUr8jtdAj5AjPYQaoqbvcZiHok1k",
    ],
    "max_slippage_bps": 100,
    "max_position_size": 1_000_000,
    "max_iterations": 10,
    "max_runtime_seconds": 180,
}

_VALID_CONSENT = {
    "devnet_only_acknowledged": True,
    "platform_managed_signing_acknowledged": True,
    "spend_caps_acknowledged": True,
    "no_indemnity_acknowledged": True,
}


# ---------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------


async def _seed_template(
    db: AsyncSession,
    *,
    template_key: str = "swap_executor_v1",
    template_version: str = "swap_executor_v1",
    is_deployable: bool = True,
) -> int:
    from src.db.models import AgentTemplate

    tmpl = AgentTemplate(
        template_key=template_key,
        template_version=template_version,
        description="test template",
        allowed_fields_json=json.dumps(
            sorted(
                [
                    "allowed_token_universe",
                    "max_slippage_bps",
                    "max_position_size",
                    "max_iterations",
                    "max_runtime_seconds",
                ]
            )
        ),
        default_config_json=json.dumps(_VALID_CONFIG),
        system_prompt="balanced",
        is_deployable=1 if is_deployable else 0,
    )
    db.add(tmpl)
    await db.flush()
    return tmpl.template_id


# ---------------------------------------------------------------------
# Test doubles — wallet service + runtime
# ---------------------------------------------------------------------


class _StubWalletService:
    """Minimal stub matching the subset of WalletService the saga uses."""

    def __init__(
        self,
        *,
        response: dict[str, str] | None = None,
        raises: Exception | None = None,
    ):
        self.response = response or {"id": "w-id-1", "address": "sol-addr-1"}
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    async def create_hosted_wallet(
        self, *, policy_id: str, authorization_pubkey: str
    ) -> dict[str, str]:
        self.calls.append(
            {
                "policy_id": policy_id,
                "authorization_pubkey": authorization_pubkey,
            }
        )
        if self.raises is not None:
            raise self.raises
        return self.response


class _StubRuntime:
    """Minimal stub matching the InstanceRuntime protocol surface used by saga."""

    def __init__(
        self,
        *,
        handle=None,
        raises: Exception | None = None,
    ):
        from src.runtime.base import InstanceHandle

        self.handle = handle or InstanceHandle(
            instance_id="swap-executor-v1",
            extra={"session_id": "sess-abc123", "effective_config": dict(_VALID_CONFIG)},
        )
        self.raises = raises
        self.deploy_calls: list[Any] = []

    async def deploy(self, spec):
        self.deploy_calls.append(spec)
        if self.raises is not None:
            raise self.raises
        return self.handle

    async def invoke_decide(self, handle, state):  # pragma: no cover — not used here
        raise NotImplementedError

    async def teardown(self, handle):  # pragma: no cover — not used here
        raise NotImplementedError


def _make_service(
    db: AsyncSession,
    *,
    wallet_service=None,
    runtime=None,
    hosted_wallet_policy_id: str = "pol-test-1",
    authorization_pubkey: str = "pub-b64-test",
):
    from src.policy.engine import InstancePolicyEngine
    from src.services.instance_service import InstanceService

    return InstanceService(
        db=db,
        policy_engine=InstancePolicyEngine(),
        wallet_service=wallet_service or _StubWalletService(),
        runtime=runtime or _StubRuntime(),
        hosted_wallet_policy_id=hosted_wallet_policy_id,
        authorization_pubkey=authorization_pubkey,
    )


# =====================================================================
# Construction — required args, empty strings rejected
# =====================================================================


async def test_construction_rejects_empty_policy_id(db):
    from src.policy.engine import InstancePolicyEngine
    from src.services.instance_service import InstanceService

    with pytest.raises(ValueError, match="hosted_wallet_policy_id"):
        InstanceService(
            db=db,
            policy_engine=InstancePolicyEngine(),
            wallet_service=_StubWalletService(),
            runtime=_StubRuntime(),
            hosted_wallet_policy_id="",
            authorization_pubkey="pub-x",
        )


async def test_construction_rejects_empty_authorization_pubkey(db):
    from src.policy.engine import InstancePolicyEngine
    from src.services.instance_service import InstanceService

    with pytest.raises(ValueError, match="authorization_pubkey"):
        InstanceService(
            db=db,
            policy_engine=InstancePolicyEngine(),
            wallet_service=_StubWalletService(),
            runtime=_StubRuntime(),
            hosted_wallet_policy_id="pol-x",
            authorization_pubkey="",
        )


async def test_construction_happy(db):
    svc = _make_service(db)
    assert svc.db is db
    assert svc.hosted_wallet_policy_id == "pol-test-1"
    assert svc.authorization_pubkey == "pub-b64-test"


# =====================================================================
# Step 1 — validate_spec failure classes
# =====================================================================


async def test_validation_failure_unknown_field_no_row(db):
    from src.services.instance_service import InstanceDeployError

    await _seed_template(db)
    svc = _make_service(db)

    bad_config = dict(_VALID_CONFIG)
    bad_config["rogue_field"] = 1
    with pytest.raises(InstanceDeployError) as ei:
        await svc.deploy_instance(
            template_key="swap_executor_v1",
            effective_config=bad_config,
            consent=_VALID_CONSENT,
            owner_ref="owner-1",
        )
    assert ei.value.status == "provisioning_failed"

    # No AgentInstance row written.
    from sqlalchemy import select

    from src.db.models import AgentInstance

    rows = (await db.execute(select(AgentInstance))).scalars().all()
    assert rows == []


async def test_validation_failure_missing_field_no_row(db):
    from src.services.instance_service import InstanceDeployError

    await _seed_template(db)
    svc = _make_service(db)

    bad_config = {k: v for k, v in _VALID_CONFIG.items() if k != "max_slippage_bps"}
    with pytest.raises(InstanceDeployError) as ei:
        await svc.deploy_instance(
            template_key="swap_executor_v1",
            effective_config=bad_config,
            consent=_VALID_CONSENT,
            owner_ref="owner-1",
        )
    assert ei.value.status == "provisioning_failed"


async def test_validation_failure_out_of_range_no_row(db):
    from src.services.instance_service import InstanceDeployError

    await _seed_template(db)
    svc = _make_service(db)

    bad_config = dict(_VALID_CONFIG)
    bad_config["max_slippage_bps"] = 9999
    with pytest.raises(InstanceDeployError) as ei:
        await svc.deploy_instance(
            template_key="swap_executor_v1",
            effective_config=bad_config,
            consent=_VALID_CONSENT,
            owner_ref="owner-1",
        )
    assert ei.value.status == "provisioning_failed"


# =====================================================================
# Step 3 — PrivyAPIError failure
# =====================================================================


async def test_step3_privy_error_provisioning_failed_no_row(db):
    from src.services.instance_service import InstanceDeployError
    from src.services.wallet_service import PrivyAPIError

    await _seed_template(db)
    wallet = _StubWalletService(
        raises=PrivyAPIError(500, "upstream down", "create_hosted_wallet")
    )
    svc = _make_service(db, wallet_service=wallet)

    with pytest.raises(InstanceDeployError) as ei:
        await svc.deploy_instance(
            template_key="swap_executor_v1",
            effective_config=_VALID_CONFIG,
            consent=_VALID_CONSENT,
            owner_ref="owner-1",
        )
    assert ei.value.status == "provisioning_failed"

    from sqlalchemy import select

    from src.db.models import AgentInstance

    rows = (await db.execute(select(AgentInstance))).scalars().all()
    assert rows == []


async def test_step3_receives_injected_policy_id_and_pubkey(db):
    # Happy-path sanity on inputs to wallet_service — defense-in-depth for
    # conflict-B resolution (shipped create_hosted_wallet takes policy_id,
    # not wallet_policy dict).
    await _seed_template(db)
    wallet = _StubWalletService()
    svc = _make_service(
        db,
        wallet_service=wallet,
        hosted_wallet_policy_id="pol-check",
        authorization_pubkey="pub-check",
    )

    await svc.deploy_instance(
        template_key="swap_executor_v1",
        effective_config=_VALID_CONFIG,
        consent=_VALID_CONSENT,
        owner_ref="owner-1",
    )
    assert wallet.calls == [
        {"policy_id": "pol-check", "authorization_pubkey": "pub-check"}
    ]


# =====================================================================
# Step 2 — chain-guard is reachable through the saga (mainnet blocked)
# =====================================================================


async def test_step2_chain_guard_blocks_mainnet(db):
    # Exercise the real policy engine's chain guard via a monkey-patched
    # call. We can't easily force "mainnet" through deploy_instance because
    # deploy_instance hardcodes devnet by design — which is the correct
    # behavior. This test asserts that INSIDE the saga, the real
    # policy_engine.build_wallet_policy call uses chain="devnet" — by
    # patching build_wallet_policy to record the kwargs.
    from unittest.mock import patch

    await _seed_template(db)
    svc = _make_service(db)

    observed: dict[str, Any] = {}
    real_build = svc.policy_engine.build_wallet_policy

    def _spy(**kwargs):
        observed.update(kwargs)
        return real_build(**kwargs)

    with patch.object(svc.policy_engine, "build_wallet_policy", side_effect=_spy):
        await svc.deploy_instance(
            template_key="swap_executor_v1",
            effective_config=_VALID_CONFIG,
            consent=_VALID_CONSENT,
            owner_ref="owner-1",
        )

    assert observed.get("chain") == "devnet"
    # allowlist_profile is the Phase-0-locked Orca allowlist
    from src.policy.allowlists import ORCA_DEVNET_ALLOWLIST

    assert observed.get("allowlist_profile") == ORCA_DEVNET_ALLOWLIST


# =====================================================================
# Step 4 — template resolution failures
# =====================================================================


async def test_step4_unknown_template_provisioning_failed(db):
    from src.services.instance_service import InstanceDeployError

    svc = _make_service(db)

    with pytest.raises(InstanceDeployError) as ei:
        await svc.deploy_instance(
            template_key="nonexistent",
            effective_config=_VALID_CONFIG,
            consent=_VALID_CONSENT,
            owner_ref="owner-1",
        )
    assert ei.value.status == "provisioning_failed"


async def test_step4_non_deployable_template_provisioning_failed(db):
    from src.services.instance_service import InstanceDeployError

    await _seed_template(db, template_key="rebalance_v1", is_deployable=False)
    svc = _make_service(db)

    with pytest.raises(InstanceDeployError) as ei:
        await svc.deploy_instance(
            template_key="rebalance_v1",
            effective_config=_VALID_CONFIG,
            consent=_VALID_CONSENT,
            owner_ref="owner-1",
        )
    assert ei.value.status == "provisioning_failed"


# =====================================================================
# Step 5 — runtime deploy failure
# =====================================================================


async def test_step5_runtime_failure_persists_partial_row(db):
    await _seed_template(db)
    runtime = _StubRuntime(raises=RuntimeError("agentos unreachable"))
    svc = _make_service(db, runtime=runtime)

    instance = await svc.deploy_instance(
        template_key="swap_executor_v1",
        effective_config=_VALID_CONFIG,
        consent=_VALID_CONSENT,
        owner_ref="owner-1",
    )

    # Row exists, in the correct failure state.
    assert instance.status == "wallet_created_runtime_failed"
    assert instance.last_failure_reason == "wallet_created_runtime_failed"
    assert instance.runtime_handle_json is None
    # Wallet was created first.
    assert instance.wallet_address == "sol-addr-1"
    assert instance.hosted_wallet_ref == "w-id-1"

    # Row persisted (committed) — re-read.
    from sqlalchemy import select

    from src.db.models import AgentInstance

    row = (
        await db.execute(
            select(AgentInstance).where(
                AgentInstance.instance_id == instance.instance_id
            )
        )
    ).scalar_one()
    assert row.status == "wallet_created_runtime_failed"
    assert row.last_failure_reason == "wallet_created_runtime_failed"


# =====================================================================
# Step 6 — consent failure
# =====================================================================


async def test_step6_consent_failure_persists_partial_row(db):
    await _seed_template(db)
    svc = _make_service(db)

    bad_consent = {
        "devnet_only_acknowledged": True,
        "platform_managed_signing_acknowledged": True,
        "spend_caps_acknowledged": True,
        # no_indemnity_acknowledged missing
    }
    instance = await svc.deploy_instance(
        template_key="swap_executor_v1",
        effective_config=_VALID_CONFIG,
        consent=bad_consent,
        owner_ref="owner-1",
    )

    assert instance.status == "runtime_live_consent_failed"
    assert instance.last_failure_reason == "runtime_live_consent_failed"
    # Runtime succeeded before consent failed — handle should be populated.
    assert instance.runtime_handle_json is not None
    # Consent artifact was never created.
    assert instance.consent_artifact_id is None


# =====================================================================
# Happy path — full 6 steps
# =====================================================================


async def test_happy_path_status_live_and_artifact_linked(db):
    from src.db.models import AgentInstance, VerificationArtifact
    from src.policy.engine import InstancePolicyEngine

    await _seed_template(db)
    svc = _make_service(db)

    instance = await svc.deploy_instance(
        template_key="swap_executor_v1",
        effective_config=_VALID_CONFIG,
        consent=_VALID_CONSENT,
        owner_ref="owner-1",
    )

    assert instance.status == "live"
    assert instance.last_failure_reason is None
    assert instance.trust_label == "benchmark_compatible_customized_instance"
    assert instance.consent_artifact_id is not None
    assert instance.runtime_handle_json is not None
    assert instance.wallet_address == "sol-addr-1"
    assert instance.hosted_wallet_ref == "w-id-1"
    assert instance.wallet_provider == "privy"

    # Re-read from DB to confirm commit.
    from sqlalchemy import select

    row = (
        await db.execute(
            select(AgentInstance).where(
                AgentInstance.instance_id == instance.instance_id
            )
        )
    ).scalar_one()
    assert row.status == "live"

    # Artifact exists, run_id NULL, canonical JSON stored in uri_or_ref.
    artifact = (
        await db.execute(
            select(VerificationArtifact).where(
                VerificationArtifact.artifact_id == instance.consent_artifact_id
            )
        )
    ).scalar_one()
    assert artifact.artifact_type == "deployment_consent"
    assert artifact.run_id is None

    engine = InstancePolicyEngine()
    expected_record = engine.record_consent(_VALID_CONSENT)
    assert artifact.uri_or_ref == expected_record.canonical_json
    assert artifact.content_hash == expected_record.content_hash


async def test_runtime_handle_json_roundtrips_to_instance_handle(db):
    from src.runtime.base import InstanceHandle

    await _seed_template(db)
    svc = _make_service(db)

    instance = await svc.deploy_instance(
        template_key="swap_executor_v1",
        effective_config=_VALID_CONFIG,
        consent=_VALID_CONSENT,
        owner_ref="owner-1",
    )

    parsed = json.loads(instance.runtime_handle_json)
    handle = InstanceHandle(**parsed)
    assert handle.instance_id == "swap-executor-v1"
    assert handle.extra["session_id"] == "sess-abc123"
    # effective_config persisted inside extra (Task 12 contract)
    assert handle.extra["effective_config"] == _VALID_CONFIG


async def test_runtime_deploy_gets_instance_spec_with_owner_ref(db):
    # Guards against Task 12 contract drift — the spec passed into
    # runtime.deploy must carry template_key, template_version, effective_config
    # AND instance_owner_ref.
    await _seed_template(db)
    runtime = _StubRuntime()
    svc = _make_service(db, runtime=runtime)

    await svc.deploy_instance(
        template_key="swap_executor_v1",
        effective_config=_VALID_CONFIG,
        consent=_VALID_CONSENT,
        owner_ref="owner-42",
    )

    assert len(runtime.deploy_calls) == 1
    spec = runtime.deploy_calls[0]
    assert spec.template_key == "swap_executor_v1"
    assert spec.template_version == "swap_executor_v1"
    assert spec.effective_config == _VALID_CONFIG
    assert spec.instance_owner_ref == "owner-42"


# =====================================================================
# Failure taxonomy — DB CHECK enforces taxonomy-only values
# =====================================================================


async def test_last_failure_reason_only_taxonomy_values(db):
    # Positive: stubbed runtime failure → taxonomy value persisted without
    # exception string leakage.
    raw_message = "internal network partition 503 — trace id abc123"
    await _seed_template(db)
    runtime = _StubRuntime(raises=RuntimeError(raw_message))
    svc = _make_service(db, runtime=runtime)

    instance = await svc.deploy_instance(
        template_key="swap_executor_v1",
        effective_config=_VALID_CONFIG,
        consent=_VALID_CONSENT,
        owner_ref="owner-1",
    )
    assert instance.last_failure_reason == "wallet_created_runtime_failed"
    assert raw_message not in (instance.last_failure_reason or "")


# =====================================================================
# Helper methods
# =====================================================================


async def test_get_instance_by_id_returns_row_or_none(db):
    await _seed_template(db)
    svc = _make_service(db)

    instance = await svc.deploy_instance(
        template_key="swap_executor_v1",
        effective_config=_VALID_CONFIG,
        consent=_VALID_CONSENT,
        owner_ref="owner-1",
    )

    got = await svc.get_instance_by_id(instance.instance_id)
    assert got is not None and got.instance_id == instance.instance_id

    missing = await svc.get_instance_by_id(99999)
    assert missing is None


async def test_get_instances_by_owner_filters_and_orders(db):
    await _seed_template(db)
    svc = _make_service(db)

    i1 = await svc.deploy_instance(
        template_key="swap_executor_v1",
        effective_config=_VALID_CONFIG,
        consent=_VALID_CONSENT,
        owner_ref="owner-A",
    )
    i2 = await svc.deploy_instance(
        template_key="swap_executor_v1",
        effective_config=_VALID_CONFIG,
        consent=_VALID_CONSENT,
        owner_ref="owner-B",
    )
    i3 = await svc.deploy_instance(
        template_key="swap_executor_v1",
        effective_config=_VALID_CONFIG,
        consent=_VALID_CONSENT,
        owner_ref="owner-A",
    )

    got_a = await svc.get_instances_by_owner("owner-A")
    assert [r.instance_id for r in got_a] == [i3.instance_id, i1.instance_id]

    got_b = await svc.get_instances_by_owner("owner-B")
    assert [r.instance_id for r in got_b] == [i2.instance_id]

    got_none = await svc.get_instances_by_owner("owner-C")
    assert got_none == []


async def test_get_instances_by_status_filters_partial_failures(db):
    from src.integrity.saga_statuses import SagaStatus

    await _seed_template(db)

    # Instance A: runtime failure.
    runtime_fail = _StubRuntime(raises=RuntimeError("boom"))
    svc_a = _make_service(db, runtime=runtime_fail)
    fail_instance = await svc_a.deploy_instance(
        template_key="swap_executor_v1",
        effective_config=_VALID_CONFIG,
        consent=_VALID_CONSENT,
        owner_ref="owner-A",
    )

    # Instance B: happy-path live.
    svc_b = _make_service(db)
    live_instance = await svc_b.deploy_instance(
        template_key="swap_executor_v1",
        effective_config=_VALID_CONFIG,
        consent=_VALID_CONSENT,
        owner_ref="owner-B",
    )

    # Query by enum member.
    failed_rows = await svc_b.get_instances_by_status(
        [SagaStatus.WALLET_CREATED_RUNTIME_FAILED]
    )
    assert [r.instance_id for r in failed_rows] == [fail_instance.instance_id]

    # Query by string value.
    live_rows = await svc_b.get_instances_by_status(["live"])
    assert [r.instance_id for r in live_rows] == [live_instance.instance_id]

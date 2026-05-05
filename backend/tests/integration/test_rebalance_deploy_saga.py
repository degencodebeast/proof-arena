"""Task 16 — RED tests for template-aware deploy saga.

Covers spec §5.2 / §13:
- deploy_instance with template_key="rebalance_executor_v1" MUST call
  validate_spec_for_template instead of validate_spec AND must NOT call
  build_wallet_policy.
- deploy_instance with template_key="swap_executor_v1" MUST call validate_spec
  AND build_wallet_policy (regression-lock).
- A bad rebalance envelope (rebalance_threshold_bps=0, below [1,5000]) MUST
  raise InstanceDeployError.

In-memory SQLite following the Task 13 / integration conftest pattern.
WalletService and InstanceRuntime are stubbed.
"""

from __future__ import annotations

import json
import os
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

os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-t16-saga")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/unused",
)


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kwargs):
    return "INTEGER"


# ---------------------------------------------------------------------------
# Fixtures — in-memory SQLite, full model schema
# ---------------------------------------------------------------------------


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
    from collections.abc import AsyncGenerator

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_template(
    db: AsyncSession,
    *,
    template_key: str,
    allowed_fields: list[str],
    default_config: dict,
) -> None:
    from src.db.models import AgentTemplate

    tmpl = AgentTemplate(
        template_key=template_key,
        template_version=template_key,
        description=f"test {template_key}",
        allowed_fields_json=json.dumps(sorted(allowed_fields)),
        default_config_json=json.dumps(default_config),
        system_prompt="test prompt",
        is_deployable=1,
    )
    db.add(tmpl)
    await db.flush()


# ---------------------------------------------------------------------------
# Test doubles — wallet service + runtime
# ---------------------------------------------------------------------------


class _StubWalletService:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    async def create_hosted_wallet(
        self, *, policy_id: str, authorization_pubkey: str
    ) -> dict[str, str]:
        self.calls.append({"policy_id": policy_id, "authorization_pubkey": authorization_pubkey})
        return {"id": "w-test-id", "address": "sol-test-addr"}


class _StubRuntime:
    def __init__(self):
        from src.runtime.base import InstanceHandle

        self.handle = InstanceHandle(
            instance_id="test-handle",
            extra={"session_id": "sess-test"},
        )
        self.deploy_calls: list[Any] = []

    async def deploy(self, spec):
        self.deploy_calls.append(spec)
        return self.handle

    async def invoke_decide(self, handle, state):  # pragma: no cover
        raise NotImplementedError

    async def teardown(self, handle):  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Spy-wrapping policy engine
# ---------------------------------------------------------------------------


def _make_spied_policy_engine(calls: dict[str, int]):
    """Return an InstancePolicyEngine with spy counters on key methods."""
    from src.policy.engine import InstancePolicyEngine

    engine = InstancePolicyEngine()
    original_validate_spec = engine.validate_spec
    original_build_wallet_policy = engine.build_wallet_policy

    def spy_validate_spec(spec):
        calls["validate_spec"] += 1
        return original_validate_spec(spec)

    def spy_build_wallet_policy(**kwargs):
        calls["build_wallet_policy"] += 1
        return original_build_wallet_policy(**kwargs)

    engine.validate_spec = spy_validate_spec
    engine.build_wallet_policy = spy_build_wallet_policy
    return engine


def _make_service(
    db: AsyncSession,
    *,
    policy_engine=None,
    wallet_service=None,
    runtime=None,
):
    from src.policy.engine import InstancePolicyEngine
    from src.services.instance_service import InstanceService

    return InstanceService(
        db=db,
        policy_engine=policy_engine or InstancePolicyEngine(),
        wallet_service=wallet_service or _StubWalletService(),
        runtime=runtime or _StubRuntime(),
        hosted_wallet_policy_id="pol-test-t16",
        authorization_pubkey="pub-b64-t16",
    )


_VALID_REBALANCE_CONSENT = {
    "devnet_only_acknowledged": True,
    "platform_managed_signing_acknowledged": True,
    "spend_caps_acknowledged": True,
    "no_indemnity_acknowledged": True,
}

_VALID_SWAP_CONSENT = {
    "devnet_only_acknowledged": True,
    "platform_managed_signing_acknowledged": True,
    "spend_caps_acknowledged": True,
    "no_indemnity_acknowledged": True,
}


# =====================================================================
# Test 1 — rebalance deploy skips build_wallet_policy + validate_spec
# =====================================================================


async def test_rebalance_deploy_skips_build_wallet_policy(db):
    """deploy_instance(template_key="rebalance_executor_v1") must NOT call
    build_wallet_policy or validate_spec (uses validate_spec_for_template instead).
    """
    from tests._rebalance_helpers import make_rebalance_envelope

    calls: dict[str, int] = {"validate_spec": 0, "build_wallet_policy": 0}
    policy_engine = _make_spied_policy_engine(calls)
    svc = _make_service(db, policy_engine=policy_engine)

    await _seed_template(
        db,
        template_key="rebalance_executor_v1",
        allowed_fields=[
            "allowed_token_universe",
            "target_allocations",
            "rebalance_threshold_bps",
            "max_slippage_bps",
            "max_position_weight",
            "max_trade_value",
            "dry_run",
        ],
        default_config=make_rebalance_envelope(),
    )

    envelope = make_rebalance_envelope()
    await svc.deploy_instance(
        template_key="rebalance_executor_v1",
        effective_config=envelope,
        consent=_VALID_REBALANCE_CONSENT,
        owner_ref="instance:test-rebalance-1",
    )

    assert calls["build_wallet_policy"] == 0, (
        f"build_wallet_policy must NOT be called for rebalance; called {calls['build_wallet_policy']} time(s)"
    )
    assert calls["validate_spec"] == 0, (
        f"validate_spec must NOT be called for rebalance (use validate_spec_for_template); "
        f"called {calls['validate_spec']} time(s)"
    )


# =====================================================================
# Test 2 — swap deploy still calls build_wallet_policy (regression lock)
# =====================================================================


async def test_swap_deploy_still_calls_build_wallet_policy(db):
    """deploy_instance(template_key="swap_executor_v1") must call both
    validate_spec (>=1) and build_wallet_policy (>=1).  Regression lock.
    """
    from src.services.template_service import SWAP_EXECUTOR_V1_SEED
    from tests._rebalance_helpers import make_swap_envelope

    calls: dict[str, int] = {"validate_spec": 0, "build_wallet_policy": 0}
    policy_engine = _make_spied_policy_engine(calls)
    svc = _make_service(db, policy_engine=policy_engine)

    default_config = json.loads(SWAP_EXECUTOR_V1_SEED["default_config_json"])
    await _seed_template(
        db,
        template_key="swap_executor_v1",
        allowed_fields=json.loads(SWAP_EXECUTOR_V1_SEED["allowed_fields_json"]),
        default_config=default_config,
    )

    envelope = make_swap_envelope()
    await svc.deploy_instance(
        template_key="swap_executor_v1",
        effective_config=envelope,
        consent=_VALID_SWAP_CONSENT,
        owner_ref="instance:test-swap-1",
    )

    assert calls["build_wallet_policy"] >= 1, (
        f"build_wallet_policy must be called for swap; called {calls['build_wallet_policy']} time(s)"
    )
    assert calls["validate_spec"] >= 1, (
        f"validate_spec must be called for swap; called {calls['validate_spec']} time(s)"
    )


# =====================================================================
# Test 3 — bad rebalance envelope raises InstanceDeployError
# =====================================================================


async def test_rebalance_deploy_invalid_envelope_raises_provisioning_failed(db):
    """An invalid rebalance envelope (rebalance_threshold_bps=0, below [1,5000])
    must raise InstanceDeployError with PROVISIONING_FAILED status.
    """
    from src.services.instance_service import InstanceDeployError
    from tests._rebalance_helpers import make_rebalance_envelope

    svc = _make_service(db)

    await _seed_template(
        db,
        template_key="rebalance_executor_v1",
        allowed_fields=[
            "allowed_token_universe",
            "target_allocations",
            "rebalance_threshold_bps",
            "max_slippage_bps",
            "max_position_weight",
            "max_trade_value",
            "dry_run",
        ],
        default_config=make_rebalance_envelope(),
    )

    bad_envelope = make_rebalance_envelope(rebalance_threshold_bps=0)

    with pytest.raises(InstanceDeployError) as exc_info:
        await svc.deploy_instance(
            template_key="rebalance_executor_v1",
            effective_config=bad_envelope,
            consent=_VALID_REBALANCE_CONSENT,
            owner_ref="instance:test-rebalance-bad",
        )

    from src.integrity.failure_taxonomy import SagaFailureReason

    assert exc_info.value.status == SagaFailureReason.PROVISIONING_FAILED.value

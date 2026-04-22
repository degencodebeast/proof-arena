"""Task 2 — RED tests for the V2 AgentInstance saga status + last_failure_reason contract.

Covers:
- ``SagaStatus`` enum shape + constructible + snake_case
- ``saga_status_values()`` helper matches enum
- Model-level CHECKs on both ``agent_instances.status`` and
  ``agent_instances.last_failure_reason``
- Column-width regression (longest value must fit)
- Drift guards between models.py tuples and the two source-of-truth enums
- Index ``idx_agent_instances_last_failure_reason`` present in ORM metadata
- Migration ``upgrade()`` / ``downgrade()`` call ordering (no live Alembic runtime)

See ``.taskmaster/docs/task2-edge-case-spec.md``.
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles


os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-t2")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/unused",
)


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kwargs):
    return "INTEGER"


@pytest_asyncio.fixture
async def engine():
    from src.db.models import Base

    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


async def _seed_template(db: AsyncSession) -> int:
    from src.db.models import AgentTemplate

    t = AgentTemplate(
        template_key="saga_status_test_template",
        template_version="saga_status_test_v1",
        description="fixture",
        allowed_fields_json="[]",
        default_config_json="{}",
        system_prompt="x",
        is_deployable=1,
    )
    db.add(t)
    await db.flush()
    return t.template_id


async def _seed_instance(
    db: AsyncSession,
    *,
    template_id: int,
    status: str | None = None,
    last_failure_reason: str | None = None,
):
    from src.db.models import AgentInstance

    kwargs = dict(
        template_id=template_id,
        template_version_at_deploy="saga_status_test_v1",
        instance_owner_ref="platform-authority",
        effective_config_json="{}",
    )
    if status is not None:
        kwargs["status"] = status
    if last_failure_reason is not None:
        kwargs["last_failure_reason"] = last_failure_reason
    db.add(AgentInstance(**kwargs))
    await db.flush()


# ----------------------------------------------------------------------
# Test 1 — SagaStatus enum members locked
# ----------------------------------------------------------------------


def test_saga_status_enum_members():
    from src.integrity.saga_statuses import SagaStatus

    assert {m.name: m.value for m in SagaStatus} == {
        "PROVISIONING": "provisioning",
        "WALLET_CREATED_RUNTIME_FAILED": "wallet_created_runtime_failed",
        "RUNTIME_LIVE_CONSENT_FAILED": "runtime_live_consent_failed",
        "PROVISIONING_FAILED": "provisioning_failed",
        "LIVE": "live",
        "PAUSED": "paused",
        "TORN_DOWN": "torn_down",
    }


# ----------------------------------------------------------------------
# Test 2 — SagaStatus constructible from value
# ----------------------------------------------------------------------


def test_saga_status_constructible_from_value():
    from src.integrity.saga_statuses import SagaStatus

    assert SagaStatus("provisioning") is SagaStatus.PROVISIONING
    assert (
        SagaStatus("wallet_created_runtime_failed")
        is SagaStatus.WALLET_CREATED_RUNTIME_FAILED
    )
    assert SagaStatus("torn_down") is SagaStatus.TORN_DOWN


# ----------------------------------------------------------------------
# Test 3 — invalid value raises ValueError
# ----------------------------------------------------------------------


def test_saga_status_invalid_value_raises():
    from src.integrity.saga_statuses import SagaStatus

    with pytest.raises(ValueError):
        SagaStatus("cancelled")  # wrong-axis ChallengeStatus value


# ----------------------------------------------------------------------
# Test 4 — enum values are lowercase_snake_case
# ----------------------------------------------------------------------


_SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")


def test_saga_status_values_are_snake_case():
    from src.integrity.saga_statuses import SagaStatus

    for m in SagaStatus:
        assert _SNAKE.match(m.value), (
            f"{m.name}: value {m.value!r} not snake_case"
        )


# ----------------------------------------------------------------------
# Test 5 — helper tuple matches enum
# ----------------------------------------------------------------------


def test_saga_status_values_helper_matches_enum():
    from src.integrity.saga_statuses import SagaStatus, saga_status_values

    assert saga_status_values() == tuple(m.value for m in SagaStatus)
    assert len(saga_status_values()) == 7


# ----------------------------------------------------------------------
# Test 6 — CHECK rejects off-contract status
# ----------------------------------------------------------------------


async def test_check_rejects_off_contract_status(db):
    template_id = await _seed_template(db)
    with pytest.raises(IntegrityError):
        await _seed_instance(
            db, template_id=template_id, status="cancelled"
        )


# ----------------------------------------------------------------------
# Test 7 — all 7 valid status values accepted
# ----------------------------------------------------------------------


async def test_all_saga_status_values_accepted(db):
    from src.integrity.saga_statuses import SagaStatus

    template_id = await _seed_template(db)
    for saga in SagaStatus:
        await _seed_instance(db, template_id=template_id, status=saga.value)
    await db.flush()


# ----------------------------------------------------------------------
# Test 8 — column width fits the longest value
# ----------------------------------------------------------------------


async def test_longest_status_value_fits_column(db):
    """Regression guard: ``wallet_created_runtime_failed`` (29 chars) must
    persist without truncation. The original ``String(20)`` column would
    have rejected this on Postgres."""
    template_id = await _seed_template(db)
    await _seed_instance(
        db,
        template_id=template_id,
        status="wallet_created_runtime_failed",
    )
    await db.flush()

    from sqlalchemy import select

    from src.db.models import AgentInstance

    row = (
        await db.execute(
            select(AgentInstance).where(AgentInstance.template_id == template_id)
        )
    ).scalar_one()
    assert row.status == "wallet_created_runtime_failed"


# ----------------------------------------------------------------------
# Test 9 — last_failure_reason NULL accepted
# ----------------------------------------------------------------------


async def test_last_failure_reason_null_accepted(db):
    """Successfully provisioned instances have NULL last_failure_reason."""
    template_id = await _seed_template(db)
    await _seed_instance(
        db,
        template_id=template_id,
        status="live",
        last_failure_reason=None,
    )
    await db.flush()


# ----------------------------------------------------------------------
# Test 10 — CHECK rejects off-contract last_failure_reason
# ----------------------------------------------------------------------


async def test_check_rejects_off_contract_last_failure_reason(db):
    template_id = await _seed_template(db)
    with pytest.raises(IntegrityError):
        await _seed_instance(
            db,
            template_id=template_id,
            status="provisioning_failed",
            last_failure_reason="arbitrary_reason",
        )


# ----------------------------------------------------------------------
# Test 11 — all 3 SagaFailureReason values accepted
# ----------------------------------------------------------------------


async def test_all_saga_failure_reason_values_accepted(db):
    from src.integrity.failure_taxonomy import SagaFailureReason

    template_id = await _seed_template(db)
    for reason in SagaFailureReason:
        await _seed_instance(
            db,
            template_id=template_id,
            status=reason.value,
            last_failure_reason=reason.value,
        )
    await db.flush()


# ----------------------------------------------------------------------
# Test 12 — drift guard: _SAGA_STATUS_VALUES matches enum
# ----------------------------------------------------------------------


def test_models_saga_status_tuple_matches_enum():
    from src.db.models import _SAGA_STATUS_VALUES
    from src.integrity.saga_statuses import SagaStatus

    assert tuple(m.value for m in SagaStatus) == _SAGA_STATUS_VALUES


# ----------------------------------------------------------------------
# Test 13 — drift guard: _SAGA_FAILURE_REASON_VALUES matches Task 1 enum
# ----------------------------------------------------------------------


def test_models_saga_failure_reason_tuple_matches_enum():
    from src.db.models import _SAGA_FAILURE_REASON_VALUES
    from src.integrity.failure_taxonomy import SagaFailureReason

    assert (
        tuple(m.value for m in SagaFailureReason) == _SAGA_FAILURE_REASON_VALUES
    )


# ----------------------------------------------------------------------
# Test 14 — index on last_failure_reason present in ORM metadata
# ----------------------------------------------------------------------


def test_last_failure_reason_index_in_metadata():
    from src.db.models import AgentInstance

    index_names = {idx.name for idx in AgentInstance.__table__.indexes}
    assert "idx_agent_instances_last_failure_reason" in index_names


# ----------------------------------------------------------------------
# Migration call-ordering tests
# ----------------------------------------------------------------------
#
# Same style as the A-4 migration tests: monkeypatch ``alembic.op``
# operations to record calls, invoke the migration module's upgrade() /
# downgrade(), and assert the expected sequence. No live Alembic runtime.


def _load_migration():
    import importlib.util
    from pathlib import Path

    mig_path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "e2f5c9a4d1b8_v2_task2_saga_status_fields.py"
    )
    spec = importlib.util.spec_from_file_location("task2_migration", mig_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_upgrade_emits_widen_then_addcol_then_index_then_checks(
    monkeypatch,
):
    """upgrade() order: alter_column (widen) → add_column → create_index
    → create_check_constraint on status → create_check_constraint on
    last_failure_reason.
    """
    import alembic.op as alembic_op

    log: list[tuple[str, tuple, dict]] = []

    def _rec(name):
        def _impl(*args, **kwargs):
            log.append((name, args, kwargs))

        return _impl

    monkeypatch.setattr(alembic_op, "alter_column", _rec("alter_column"))
    monkeypatch.setattr(alembic_op, "add_column", _rec("add_column"))
    monkeypatch.setattr(alembic_op, "create_index", _rec("create_index"))
    monkeypatch.setattr(
        alembic_op, "create_check_constraint", _rec("create_check_constraint")
    )

    migration = _load_migration()
    migration.upgrade()

    # Sequence check
    names = [entry[0] for entry in log]
    assert names == [
        "alter_column",
        "add_column",
        "create_index",
        "create_check_constraint",
        "create_check_constraint",
    ], names

    # alter_column widens status on agent_instances
    assert log[0][1][0] == "agent_instances"
    assert log[0][1][1] == "status"

    # add_column targets agent_instances
    assert log[1][1][0] == "agent_instances"

    # create_index targets the new column on agent_instances
    create_index_args = log[2][1]
    # op.create_index(name, table, columns, ...)
    assert create_index_args[0] == "idx_agent_instances_last_failure_reason"
    assert create_index_args[1] == "agent_instances"
    assert "last_failure_reason" in list(create_index_args[2])

    # Two CHECK constraints — first on status, second on last_failure_reason
    first_ck = log[3][1]
    assert first_ck[0] == "ck_agent_instances_status"
    assert first_ck[1] == "agent_instances"
    assert "provisioning" in first_ck[2]
    assert "wallet_created_runtime_failed" in first_ck[2]

    second_ck = log[4][1]
    assert second_ck[0] == "ck_agent_instances_last_failure_reason"
    assert second_ck[1] == "agent_instances"
    # NULL allowed explicitly in the predicate
    assert "IS NULL" in second_ck[2] or "IS  NULL" in second_ck[2]
    assert "provisioning_failed" in second_ck[2]


def test_migration_downgrade_drops_checks_then_index_then_column(monkeypatch):
    """downgrade() order: drop last_failure_reason CHECK → drop status CHECK
    → drop index → drop column. Column width intentionally left at String(32).
    """
    import alembic.op as alembic_op

    log: list[tuple[str, tuple, dict]] = []

    def _rec(name):
        def _impl(*args, **kwargs):
            log.append((name, args, kwargs))

        return _impl

    monkeypatch.setattr(alembic_op, "drop_constraint", _rec("drop_constraint"))
    monkeypatch.setattr(alembic_op, "drop_index", _rec("drop_index"))
    monkeypatch.setattr(alembic_op, "drop_column", _rec("drop_column"))

    migration = _load_migration()
    migration.downgrade()

    names = [entry[0] for entry in log]
    assert names == [
        "drop_constraint",
        "drop_constraint",
        "drop_index",
        "drop_column",
    ], names

    # Inverse of upgrade order — last_failure_reason CHECK first (most-recent),
    # then status CHECK.
    assert log[0][1][0] == "ck_agent_instances_last_failure_reason"
    assert log[0][1][1] == "agent_instances"
    assert log[0][2].get("type_") == "check"

    assert log[1][1][0] == "ck_agent_instances_status"
    assert log[1][1][1] == "agent_instances"
    assert log[1][2].get("type_") == "check"

    # Drop the index
    assert log[2][1][0] == "idx_agent_instances_last_failure_reason"
    # drop_index may take table kwarg or positional — either shape OK
    assert (
        (len(log[2][1]) > 1 and log[2][1][1] == "agent_instances")
        or log[2][2].get("table_name") == "agent_instances"
    )

    # Drop the column
    assert log[3][1][0] == "agent_instances"
    assert log[3][1][1] == "last_failure_reason"

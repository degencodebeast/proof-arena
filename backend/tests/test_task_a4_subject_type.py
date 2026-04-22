"""Task 7 / A-4 — RED tests for the V2 subject_type contract.

Covers:
- ``SubjectType`` enum shape + constructible-from-value + snake_case
- ``subject_type_values()`` helper matches enum
- DB CHECK constraint applied to BOTH ``agents`` and ``rank_snapshots``
- Axis-confusion rejection (``external_custom_runtime`` is a trust-label
  value, not a subject_type value)
- Drift guard between models.py tuple and the enum
- Column defaults preserved on both tables

See ``.taskmaster/docs/task7-edge-case-spec.md``.
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles


os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-a4")
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


async def _seed_agent(db: AsyncSession, *, subject_type: str | None = None) -> int:
    from src.db.models import Agent

    kwargs = dict(
        privy_user_id="u",
        owner_wallet="w" * 44,
        display_name="t",
        submission_hash="a" * 64,
        system_prompt="x",
    )
    if subject_type is not None:
        kwargs["subject_type"] = subject_type
    agent = Agent(**kwargs)
    db.add(agent)
    await db.flush()
    return agent.agent_id


async def _seed_rank_snapshot(
    db: AsyncSession, *, agent_id: int, subject_type: str | None = None
) -> int:
    from src.db.models import RankSnapshot

    kwargs = dict(
        agent_id=agent_id,
        rank_version="rank_v1",
        score=50.0,
        score_inputs_json="{}",
        score_breakdown_json="{}",
    )
    if subject_type is not None:
        kwargs["subject_type"] = subject_type
    snap = RankSnapshot(**kwargs)
    db.add(snap)
    await db.flush()
    return snap.snapshot_id


# ----------------------------------------------------------------------
# Test 1 — enum members locked
# ----------------------------------------------------------------------


def test_subject_type_enum_members():
    from src.integrity.subject_types import SubjectType

    assert {m.name: m.value for m in SubjectType} == {
        "CANONICAL_TEMPLATE": "canonical_template",
        "CUSTOMIZED_INSTANCE": "customized_instance",
    }


# ----------------------------------------------------------------------
# Test 2 — constructible from value
# ----------------------------------------------------------------------


def test_subject_type_constructible_from_value():
    from src.integrity.subject_types import SubjectType

    assert SubjectType("canonical_template") is SubjectType.CANONICAL_TEMPLATE
    assert SubjectType("customized_instance") is SubjectType.CUSTOMIZED_INSTANCE


# ----------------------------------------------------------------------
# Test 3 — invalid value raises ValueError
# ----------------------------------------------------------------------


def test_subject_type_invalid_value_raises():
    from src.integrity.subject_types import SubjectType

    with pytest.raises(ValueError):
        SubjectType("invalid_subject")


# ----------------------------------------------------------------------
# Test 4 — enum values are lowercase_snake_case
# ----------------------------------------------------------------------


_SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")


def test_subject_type_values_are_snake_case():
    from src.integrity.subject_types import SubjectType

    for m in SubjectType:
        assert _SNAKE.match(m.value), (
            f"{m.name}: value {m.value!r} not snake_case"
        )


# ----------------------------------------------------------------------
# Test 5 — helper tuple matches enum
# ----------------------------------------------------------------------


def test_subject_type_values_helper_matches_enum():
    from src.integrity.subject_types import SubjectType, subject_type_values

    assert subject_type_values() == tuple(m.value for m in SubjectType)
    assert len(subject_type_values()) == 2


# ----------------------------------------------------------------------
# Test 6 — CHECK rejects off-contract agents.subject_type
# ----------------------------------------------------------------------


async def test_check_rejects_off_contract_agent_subject_type(db):
    with pytest.raises(IntegrityError):
        await _seed_agent(db, subject_type="invalid_subject")


# ----------------------------------------------------------------------
# Test 7 — CHECK rejects off-contract rank_snapshots.subject_type
# ----------------------------------------------------------------------


async def test_check_rejects_off_contract_rank_snapshot_subject_type(db):
    # Seed the prerequisite Agent first so the RankSnapshot FK resolves.
    agent_id = await _seed_agent(db)
    with pytest.raises(IntegrityError):
        await _seed_rank_snapshot(
            db, agent_id=agent_id, subject_type="invalid_subject"
        )


# ----------------------------------------------------------------------
# Test 8 — both enum values accepted on agents
# ----------------------------------------------------------------------


async def test_both_enum_values_accepted_on_agents(db):
    from src.integrity.subject_types import SubjectType

    for label in SubjectType:
        await _seed_agent(db, subject_type=label.value)
    await db.flush()


# ----------------------------------------------------------------------
# Test 9 — both enum values accepted on rank_snapshots
# ----------------------------------------------------------------------


async def test_both_enum_values_accepted_on_rank_snapshots(db):
    from src.integrity.subject_types import SubjectType

    agent_id = await _seed_agent(db)
    for label in SubjectType:
        await _seed_rank_snapshot(
            db, agent_id=agent_id, subject_type=label.value
        )
    await db.flush()


# ----------------------------------------------------------------------
# Test 10 — axis-confusion guard (trust-label value on subject_type column)
# ----------------------------------------------------------------------


async def test_trust_label_value_rejected_on_subject_type(db):
    """``external_custom_runtime`` is a trust-label axis value; it must NOT
    be acceptable as a subject_type. Guards against cross-axis confusion.
    """
    with pytest.raises(IntegrityError):
        await _seed_agent(db, subject_type="external_custom_runtime")


# ----------------------------------------------------------------------
# Test 11 — drift guard between models.py and the enum
# ----------------------------------------------------------------------


def test_models_subject_type_tuple_matches_enum():
    """models.py cannot import from src.integrity (circular via the integrity
    package init). The duplicated tuple must stay byte-equal to the enum.
    """
    from src.db.models import _SUBJECT_TYPE_VALUES
    from src.integrity.subject_types import SubjectType

    assert tuple(m.value for m in SubjectType) == _SUBJECT_TYPE_VALUES


# ----------------------------------------------------------------------
# Test 12 — default unchanged on agents
# ----------------------------------------------------------------------


async def test_default_subject_type_unchanged_on_agents(db):
    from src.db.models import Agent

    agent_id = await _seed_agent(db)
    row = (
        await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    ).scalar_one()
    assert row.subject_type == "canonical_template"


# ----------------------------------------------------------------------
# Test 13 — default unchanged on rank_snapshots
# ----------------------------------------------------------------------


async def test_default_subject_type_unchanged_on_rank_snapshots(db):
    from src.db.models import RankSnapshot

    agent_id = await _seed_agent(db)
    snap_id = await _seed_rank_snapshot(db, agent_id=agent_id)
    row = (
        await db.execute(
            select(RankSnapshot).where(RankSnapshot.snapshot_id == snap_id)
        )
    ).scalar_one()
    assert row.subject_type == "canonical_template"


# ----------------------------------------------------------------------
# Migration-call tests — verify upgrade()/downgrade() behavior directly
# ----------------------------------------------------------------------
#
# These tests patch ``alembic.op.execute``, ``alembic.op.create_check_constraint``,
# and ``alembic.op.drop_constraint`` so they record calls without needing a live
# Alembic runtime, then invoke the migration's ``upgrade()`` / ``downgrade()``
# and assert the expected call sequence. This is complementary to the
# model-level CHECK tests above: those prove the schema behaves correctly once
# the migration has been applied; these prove the migration itself emits the
# correct SQL in the correct order.


def _load_migration():
    """Import the A-4 migration module by file path (Alembic filenames start
    with a revision hash, not a valid Python identifier, so dotted import
    doesn't work).
    """
    import importlib.util
    from pathlib import Path

    mig_path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "d7a412c8b3e9_v2_a4_subject_type_backfill_and_check.py"
    )
    spec = importlib.util.spec_from_file_location("a4_migration", mig_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_upgrade_emits_backfill_then_checks(monkeypatch):
    """upgrade() runs both UPDATE backfills, then creates both CHECKs, in order."""
    from unittest.mock import MagicMock

    import alembic.op as alembic_op

    execute_mock = MagicMock(name="op.execute")
    create_check_mock = MagicMock(name="op.create_check_constraint")
    monkeypatch.setattr(alembic_op, "execute", execute_mock)
    monkeypatch.setattr(
        alembic_op, "create_check_constraint", create_check_mock
    )

    migration = _load_migration()
    migration.upgrade()

    # Both backfills ran, in order: agents first, rank_snapshots second.
    assert execute_mock.call_count == 2
    first_sql = execute_mock.call_args_list[0].args[0]
    second_sql = execute_mock.call_args_list[1].args[0]
    assert "UPDATE agents SET subject_type = 'canonical_template'" in first_sql
    assert "WHERE subject_type IS NULL OR subject_type = ''" in first_sql
    assert (
        "UPDATE rank_snapshots SET subject_type = 'canonical_template'"
        in second_sql
    )
    assert "WHERE subject_type IS NULL OR subject_type = ''" in second_sql

    # Both CHECKs created, in order: agents first, rank_snapshots second.
    assert create_check_mock.call_count == 2
    first_check = create_check_mock.call_args_list[0].args
    second_check = create_check_mock.call_args_list[1].args
    assert first_check[0] == "ck_agents_subject_type"
    assert first_check[1] == "agents"
    assert "canonical_template" in first_check[2]
    assert "customized_instance" in first_check[2]
    assert second_check[0] == "ck_rank_snapshots_subject_type"
    assert second_check[1] == "rank_snapshots"


def test_migration_downgrade_drops_checks_then_reverts_backfill(monkeypatch):
    """downgrade() drops both CHECKs, then runs both inverse UPDATEs, in order."""
    from unittest.mock import MagicMock

    import alembic.op as alembic_op

    # Single recorder captures calls in order across op.drop_constraint and
    # op.execute so we can assert on interleaving.
    call_log: list[tuple[str, tuple, dict]] = []

    def _rec(name):
        def _impl(*args, **kwargs):
            call_log.append((name, args, kwargs))

        return _impl

    monkeypatch.setattr(alembic_op, "drop_constraint", _rec("drop_constraint"))
    monkeypatch.setattr(alembic_op, "execute", _rec("execute"))

    migration = _load_migration()
    migration.downgrade()

    # Expected sequence: drop rank_snapshots CHECK → drop agents CHECK →
    # inverse UPDATE rank_snapshots → inverse UPDATE agents.
    assert len(call_log) == 4

    assert call_log[0][0] == "drop_constraint"
    assert call_log[0][1][0] == "ck_rank_snapshots_subject_type"
    assert call_log[0][1][1] == "rank_snapshots"
    assert call_log[0][2].get("type_") == "check"

    assert call_log[1][0] == "drop_constraint"
    assert call_log[1][1][0] == "ck_agents_subject_type"
    assert call_log[1][1][1] == "agents"
    assert call_log[1][2].get("type_") == "check"

    # Inverse updates after constraints are gone.
    assert call_log[2][0] == "execute"
    third_sql = call_log[2][1][0]
    assert "UPDATE rank_snapshots SET subject_type = NULL" in third_sql
    assert "WHERE subject_type = 'canonical_template'" in third_sql

    assert call_log[3][0] == "execute"
    fourth_sql = call_log[3][1][0]
    assert "UPDATE agents SET subject_type = NULL" in fourth_sql
    assert "WHERE subject_type = 'canonical_template'" in fourth_sql

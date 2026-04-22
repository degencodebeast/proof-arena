"""Task 6 / A-5 — RED tests for the V2 Trust Label contract.

Covers the Python enum, the model-level CHECK constraint on
``agent_instances.trust_label``, and the drift-guard tying
``db.models._TRUST_LABEL_VALUES`` to the enum.

See ``.taskmaster/docs/task6-edge-case-spec.md``.
"""

from __future__ import annotations

import json
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


os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-a5")
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
# Helpers — seed a minimal template so we can insert AgentInstance rows
# ----------------------------------------------------------------------


async def _seed_template(db: AsyncSession) -> int:
    from src.db.models import AgentTemplate

    t = AgentTemplate(
        template_key="trust_label_test_template",
        template_version="trust_label_test_v1",
        description="fixture",
        allowed_fields_json="[]",
        default_config_json="{}",
        system_prompt="x",
        is_deployable=1,
    )
    db.add(t)
    await db.flush()
    return t.template_id


async def _seed_instance(db: AsyncSession, *, template_id: int, trust_label: str):
    from src.db.models import AgentInstance

    db.add(
        AgentInstance(
            template_id=template_id,
            template_version_at_deploy="trust_label_test_v1",
            instance_owner_ref="platform-authority",
            effective_config_json="{}",
            trust_label=trust_label,
        )
    )
    await db.flush()


# ----------------------------------------------------------------------
# Test 1 — enum members locked
# ----------------------------------------------------------------------


def test_trust_label_enum_members():
    from src.integrity.trust_labels import TrustLabel

    assert {m.name: m.value for m in TrustLabel} == {
        "BENCHMARKED_CANONICAL_TEMPLATE": "benchmarked_canonical_template",
        "BENCHMARK_COMPATIBLE_CUSTOMIZED_INSTANCE": (
            "benchmark_compatible_customized_instance"
        ),
        "EXTERNAL_CUSTOM_RUNTIME": "external_custom_runtime",
    }


# ----------------------------------------------------------------------
# Test 2 — constructing from string returns correct member
# ----------------------------------------------------------------------


def test_trust_label_constructible_from_value():
    from src.integrity.trust_labels import TrustLabel

    assert (
        TrustLabel("benchmarked_canonical_template")
        is TrustLabel.BENCHMARKED_CANONICAL_TEMPLATE
    )
    assert (
        TrustLabel("benchmark_compatible_customized_instance")
        is TrustLabel.BENCHMARK_COMPATIBLE_CUSTOMIZED_INSTANCE
    )
    assert (
        TrustLabel("external_custom_runtime") is TrustLabel.EXTERNAL_CUSTOM_RUNTIME
    )


# ----------------------------------------------------------------------
# Test 3 — invalid string raises ValueError
# ----------------------------------------------------------------------


def test_trust_label_invalid_value_raises():
    from src.integrity.trust_labels import TrustLabel

    with pytest.raises(ValueError):
        TrustLabel("invalid_label")


# ----------------------------------------------------------------------
# Test 4 — enum values are lowercase_snake_case
# ----------------------------------------------------------------------


_SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")


def test_trust_label_values_are_snake_case():
    from src.integrity.trust_labels import TrustLabel

    for m in TrustLabel:
        assert _SNAKE.match(m.value), f"{m.name}: value {m.value!r} not snake_case"


# ----------------------------------------------------------------------
# Test 5 — helper tuple matches enum exactly
# ----------------------------------------------------------------------


def test_trust_label_values_helper_matches_enum():
    from src.integrity.trust_labels import TrustLabel, trust_label_values

    assert trust_label_values() == tuple(m.value for m in TrustLabel)
    assert len(trust_label_values()) == 3


# ----------------------------------------------------------------------
# Test 6 — CheckConstraint rejects off-contract value
# ----------------------------------------------------------------------


async def test_check_rejects_off_contract_trust_label(db):
    template_id = await _seed_template(db)
    with pytest.raises(IntegrityError):
        await _seed_instance(
            db, template_id=template_id, trust_label="invalid_label"
        )


# ----------------------------------------------------------------------
# Test 7 — all 3 enum values accepted by the CHECK
# ----------------------------------------------------------------------


async def test_all_enum_values_accepted(db):
    from src.integrity.trust_labels import TrustLabel

    template_id = await _seed_template(db)
    for label in TrustLabel:
        await _seed_instance(
            db, template_id=template_id, trust_label=label.value
        )
    await db.flush()


# ----------------------------------------------------------------------
# Test 8 — drift guard between models.py and the enum
# ----------------------------------------------------------------------


def test_models_trust_label_tuple_matches_enum():
    """models.py cannot import from src.integrity (circular via the integrity
    package init). It duplicates the enum values as a tuple; this test fails
    loudly on any drift.
    """
    from src.db.models import _TRUST_LABEL_VALUES
    from src.integrity.trust_labels import TrustLabel

    assert tuple(m.value for m in TrustLabel) == _TRUST_LABEL_VALUES


# ----------------------------------------------------------------------
# Test 9 — default trust_label still persists unchanged
# ----------------------------------------------------------------------


async def test_default_trust_label_unchanged(db):
    from src.db.models import AgentInstance

    template_id = await _seed_template(db)
    # Construct without specifying trust_label -> column default fires
    db.add(
        AgentInstance(
            template_id=template_id,
            template_version_at_deploy="trust_label_test_v1",
            instance_owner_ref="platform-authority",
            effective_config_json="{}",
        )
    )
    await db.flush()
    # Round-trip read
    from sqlalchemy import select
    row = (
        await db.execute(select(AgentInstance).where(AgentInstance.template_id == template_id))
    ).scalar_one()
    assert row.trust_label == "benchmark_compatible_customized_instance"

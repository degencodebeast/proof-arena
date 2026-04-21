"""Task 3 / A-1 — RED tests for the V2 Template Service.

Covers:
- Envelope-locked registration (5-field contract)
- Unique template_key enforcement
- Catalog reads (by key, list, deployable-only)
- Flagship-info read (locked trust-label contract — reads from
  ``agent_instances.trust_label``, never from ``agents``)
- Canonical ``swap_executor_v1`` seed derived from Strategy Builder Lite
  BALANCED template's system_prompt

See ``.taskmaster/docs/task3-edge-case-spec.md``.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles


os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-a1")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/unused",
)


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kwargs):
    return "INTEGER"


@pytest_asyncio.fixture
async def engine():
    from sqlalchemy import event

    from src.db.models import Base

    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # Enable FK enforcement on SQLite so the negative FK test actually trips
    # an IntegrityError. SQLite's default is OFF; pragma is connection-scoped.
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
# Helpers
# ---------------------------------------------------------------------


_V2_ENVELOPE = sorted(
    [
        "allowed_token_universe",
        "max_slippage_bps",
        "max_position_size",
        "max_iterations",
        "max_runtime_seconds",
    ]
)

_V2_DEFAULT_CONFIG = {
    "allowed_token_universe": [
        "So11111111111111111111111111111111111111112",
        "BRjpCHtyQLNCo8gqRUr8jtdAj5AjPYQaoqbvcZiHok1k",
    ],
    "max_slippage_bps": 100,
    "max_position_size": 1_000_000,
    "max_iterations": 10,
    "max_runtime_seconds": 180,
}


def _valid_register_kwargs(**overrides) -> dict:
    base = {
        "template_key": "swap_executor_v1",
        "template_version": "swap_executor_v1",
        "description": "Execute a fixed-basket swap on devnet.",
        "allowed_fields_json": json.dumps(_V2_ENVELOPE),
        "default_config_json": json.dumps(_V2_DEFAULT_CONFIG),
        "system_prompt": "Balance risk and opportunity.",
        "is_deployable": True,
    }
    base.update(overrides)
    return base


async def _seed_agent(db: AsyncSession, *, subject_type: str = "canonical_template") -> int:
    from src.db.models import Agent

    agent = Agent(
        privy_user_id="platform",
        owner_wallet="w" * 44,
        display_name="flagship_swap_executor",
        submission_hash="a" * 64,
        system_prompt="x",
        subject_type=subject_type,
    )
    db.add(agent)
    await db.flush()
    return agent.agent_id


async def _seed_agent_instance(
    db: AsyncSession,
    *,
    template_id: int,
    trust_label: str,
    status: str = "live",
) -> None:
    from src.db.models import AgentInstance

    db.add(
        AgentInstance(
            template_id=template_id,
            template_version_at_deploy="swap_executor_v1",
            instance_owner_ref="platform-authority",
            effective_config_json=json.dumps(_V2_DEFAULT_CONFIG),
            trust_label=trust_label,
            status=status,
        )
    )
    await db.flush()


# ---------------------------------------------------------------------
# Test 1 — instantiation
# ---------------------------------------------------------------------


async def test_service_instantiates(db):
    from src.policy.engine import InstancePolicyEngine
    from src.services.template_service import TemplateService

    svc = TemplateService(db)
    assert svc.db is db
    assert isinstance(svc.policy_engine, InstancePolicyEngine)


# ---------------------------------------------------------------------
# Test 2 — register_template persists the row
# ---------------------------------------------------------------------


async def test_register_template_persists_row(db):
    from src.services.template_service import TemplateService

    svc = TemplateService(db)
    t = await svc.register_template(**_valid_register_kwargs())
    await db.commit()

    assert t.template_id is not None
    assert t.template_key == "swap_executor_v1"
    assert t.template_version == "swap_executor_v1"
    assert bool(t.is_deployable) is True
    # allowed_fields_json round-trips
    assert sorted(json.loads(t.allowed_fields_json)) == _V2_ENVELOPE


# ---------------------------------------------------------------------
# Test 3 — missing envelope field rejected
# ---------------------------------------------------------------------


async def test_register_rejects_missing_envelope_field(db):
    from src.services.template_service import (
        TemplateService,
        TemplateValidationError,
    )

    svc = TemplateService(db)
    bad = _valid_register_kwargs(
        allowed_fields_json=json.dumps([f for f in _V2_ENVELOPE if f != "max_iterations"]),
    )
    with pytest.raises(TemplateValidationError):
        await svc.register_template(**bad)


# ---------------------------------------------------------------------
# Test 4 — extra envelope field rejected
# ---------------------------------------------------------------------


async def test_register_rejects_extra_envelope_field(db):
    from src.services.template_service import (
        TemplateService,
        TemplateValidationError,
    )

    svc = TemplateService(db)
    bad = _valid_register_kwargs(
        allowed_fields_json=json.dumps(_V2_ENVELOPE + ["custom_prompt"]),
    )
    with pytest.raises(TemplateValidationError):
        await svc.register_template(**bad)


# ---------------------------------------------------------------------
# Test 5 — malformed allowed_fields JSON rejected
# ---------------------------------------------------------------------


async def test_register_rejects_malformed_allowed_fields_json(db):
    from src.services.template_service import (
        TemplateService,
        TemplateValidationError,
    )

    svc = TemplateService(db)
    bad = _valid_register_kwargs(allowed_fields_json="{not: valid json]")
    with pytest.raises(TemplateValidationError):
        await svc.register_template(**bad)


# ---------------------------------------------------------------------
# Test 6 — duplicate template_key rejected
# ---------------------------------------------------------------------


async def test_duplicate_key_rejected(db):
    from src.services.template_service import (
        TemplateAlreadyExistsError,
        TemplateService,
    )

    svc = TemplateService(db)
    await svc.register_template(**_valid_register_kwargs())
    await db.commit()
    with pytest.raises(TemplateAlreadyExistsError):
        await svc.register_template(**_valid_register_kwargs())


# ---------------------------------------------------------------------
# Test 7 — get_template_by_key found
# ---------------------------------------------------------------------


async def test_get_template_by_key_found(db):
    from src.services.template_service import TemplateService

    svc = TemplateService(db)
    await svc.register_template(**_valid_register_kwargs())
    await db.commit()
    got = await svc.get_template_by_key("swap_executor_v1")
    assert got is not None
    assert got.template_key == "swap_executor_v1"


# ---------------------------------------------------------------------
# Test 8 — get_template_by_key missing returns None
# ---------------------------------------------------------------------


async def test_get_template_by_key_missing_returns_none(db):
    from src.services.template_service import TemplateService

    svc = TemplateService(db)
    assert await svc.get_template_by_key("does_not_exist") is None


# ---------------------------------------------------------------------
# Test 9 — list_templates returns all
# ---------------------------------------------------------------------


async def test_list_templates_returns_all(db):
    """list_templates returns all templates, ordered by created_at desc.

    Uses explicit created_at overrides to make the ordering deterministic.
    """
    from datetime import datetime, timezone

    from src.services.template_service import TemplateService

    svc = TemplateService(db)
    t1 = await svc.register_template(**_valid_register_kwargs())
    t2 = await svc.register_template(
        **_valid_register_kwargs(
            template_key="another_v1", template_version="another_v1"
        )
    )
    t1.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t2.created_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
    await db.commit()

    rows = await svc.list_templates()
    assert [r.template_key for r in rows] == ["another_v1", "swap_executor_v1"]


# ---------------------------------------------------------------------
# Test 10 — list_templates(deployable_only=True) filters non-deployable
# ---------------------------------------------------------------------


async def test_list_deployable_only_excludes_signposts(db):
    from src.services.template_service import TemplateService

    svc = TemplateService(db)
    await svc.register_template(**_valid_register_kwargs())
    await svc.register_template(
        **_valid_register_kwargs(
            template_key="signpost_v1",
            template_version="signpost_v1",
            is_deployable=False,
        )
    )
    await db.commit()

    all_rows = await svc.list_templates()
    assert len(all_rows) == 2

    deployable = await svc.list_templates(deployable_only=True)
    assert [r.template_key for r in deployable] == ["swap_executor_v1"]


# ---------------------------------------------------------------------
# Test 11 — flagship_info with no agent linked → label None
# ---------------------------------------------------------------------


async def test_flagship_info_no_agent_linked(db):
    from src.services.template_service import TemplateService

    svc = TemplateService(db)
    await svc.register_template(**_valid_register_kwargs())
    await db.commit()

    info = await svc.get_template_with_flagship_info("swap_executor_v1")
    assert info is not None
    assert info["template_key"] == "swap_executor_v1"
    assert info["benchmark_subject_agent_id"] is None
    assert info["flagship_trust_label"] is None
    # response shape: JSON-decoded allowed_fields + default_config
    assert sorted(info["allowed_fields"]) == _V2_ENVELOPE
    assert info["default_config"]["max_slippage_bps"] == 100


# ---------------------------------------------------------------------
# Test 12 — flagship_info with agent linked but no instance → label None
# ---------------------------------------------------------------------


async def test_flagship_info_agent_linked_no_instance(db):
    from src.services.template_service import TemplateService

    svc = TemplateService(db)
    agent_id = await _seed_agent(db)
    await svc.register_template(
        **_valid_register_kwargs(benchmark_subject_agent_id=agent_id)
    )
    await db.commit()

    info = await svc.get_template_with_flagship_info("swap_executor_v1")
    assert info is not None
    assert info["benchmark_subject_agent_id"] == agent_id
    assert info["flagship_trust_label"] is None


# ---------------------------------------------------------------------
# Test 13 — flagship_info with a live flagship instance → label set
# ---------------------------------------------------------------------


async def test_flagship_info_with_live_flagship(db):
    from src.services.template_service import TemplateService

    svc = TemplateService(db)
    agent_id = await _seed_agent(db)
    t = await svc.register_template(
        **_valid_register_kwargs(benchmark_subject_agent_id=agent_id)
    )
    await _seed_agent_instance(
        db,
        template_id=t.template_id,
        trust_label="benchmarked_canonical_template",
        status="live",
    )
    await db.commit()

    info = await svc.get_template_with_flagship_info("swap_executor_v1")
    assert info is not None
    assert info["flagship_trust_label"] == "benchmarked_canonical_template"


# ---------------------------------------------------------------------
# Test 14 — only customized-instance rows → flagship label None
# ---------------------------------------------------------------------


async def test_flagship_info_customized_only_returns_none(db):
    from src.services.template_service import TemplateService

    svc = TemplateService(db)
    agent_id = await _seed_agent(db)
    t = await svc.register_template(
        **_valid_register_kwargs(benchmark_subject_agent_id=agent_id)
    )
    # A customized instance linked to the same template must NOT surface as flagship.
    await _seed_agent_instance(
        db,
        template_id=t.template_id,
        trust_label="benchmark_compatible_customized_instance",
        status="live",
    )
    await db.commit()

    info = await svc.get_template_with_flagship_info("swap_executor_v1")
    assert info is not None
    assert info["flagship_trust_label"] is None


# ---------------------------------------------------------------------
# Test 15 — flagship_info on missing key → None
# ---------------------------------------------------------------------


async def test_flagship_info_missing_key(db):
    from src.services.template_service import TemplateService

    svc = TemplateService(db)
    assert await svc.get_template_with_flagship_info("nope") is None


# ---------------------------------------------------------------------
# Test 16 — swap_executor_v1 seed uses BALANCED Builder Lite system_prompt
# ---------------------------------------------------------------------


# Mirrors frontend/src/components/strategy/StrategyBuilderLite.tsx :: BALANCED.system_prompt
_BALANCED_SYSTEM_PROMPT = (
    "Balance risk and opportunity. Use moderate slippage tolerance. "
    "Complete the required basket while avoiding unnecessary invalid "
    "actions or excessive waiting."
)


def test_swap_executor_v1_seed_matches_balanced_builder():
    from src.services.template_service import SWAP_EXECUTOR_V1_SEED

    assert SWAP_EXECUTOR_V1_SEED["template_key"] == "swap_executor_v1"
    assert SWAP_EXECUTOR_V1_SEED["template_version"] == "swap_executor_v1"
    assert SWAP_EXECUTOR_V1_SEED["is_deployable"] is True
    assert SWAP_EXECUTOR_V1_SEED["system_prompt"] == _BALANCED_SYSTEM_PROMPT
    # Allowed fields must match the V2 5-field envelope exactly.
    assert sorted(json.loads(SWAP_EXECUTOR_V1_SEED["allowed_fields_json"])) == _V2_ENVELOPE


# ---------------------------------------------------------------------
# Fix-pass tests — default_config validation, IntegrityError correctness
# ---------------------------------------------------------------------


async def test_register_rejects_malformed_default_config_json(db):
    """default_config_json that is not parseable JSON must be rejected."""
    from src.services.template_service import (
        TemplateService,
        TemplateValidationError,
    )

    svc = TemplateService(db)
    bad = _valid_register_kwargs(default_config_json="not-a-json")
    with pytest.raises(TemplateValidationError):
        await svc.register_template(**bad)


async def test_register_rejects_non_dict_default_config(db):
    """default_config_json that decodes to a non-dict must be rejected."""
    from src.services.template_service import (
        TemplateService,
        TemplateValidationError,
    )

    svc = TemplateService(db)
    bad = _valid_register_kwargs(
        default_config_json=json.dumps(["not", "a", "dict"])
    )
    with pytest.raises(TemplateValidationError):
        await svc.register_template(**bad)


async def test_register_rejects_policy_invalid_default_config(db):
    """default_config_json that violates InstancePolicyEngine.validate_spec is rejected."""
    from src.services.template_service import (
        TemplateService,
        TemplateValidationError,
    )

    svc = TemplateService(db)
    over_limit_config = dict(_V2_DEFAULT_CONFIG)
    # _MAX_SLIPPAGE_BPS_LIMIT = 500 in policy/engine.py; 99_999 is clearly out.
    over_limit_config["max_slippage_bps"] = 99_999
    bad = _valid_register_kwargs(
        default_config_json=json.dumps(over_limit_config)
    )
    with pytest.raises(TemplateValidationError):
        await svc.register_template(**bad)


async def test_bad_benchmark_subject_agent_id_does_not_raise_already_exists(db):
    """A FK violation must NOT be reported as TemplateAlreadyExistsError.

    Only a genuine template_key collision is a duplicate-key error. Other
    IntegrityErrors (e.g., dangling FK on benchmark_subject_agent_id) must
    surface as IntegrityError, not get miscategorised.
    """
    from sqlalchemy.exc import IntegrityError

    from src.services.template_service import (
        TemplateAlreadyExistsError,
        TemplateService,
    )

    svc = TemplateService(db)
    # 999_999 is not a valid agents.agent_id — FK should fire.
    kwargs = _valid_register_kwargs(benchmark_subject_agent_id=999_999)

    with pytest.raises(IntegrityError):
        await svc.register_template(**kwargs)
    # Explicitly not a duplicate-key error.
    # (If the TemplateAlreadyExistsError branch had fired, pytest would have
    # caught that instead of IntegrityError.)
    # Guard against a regression where the exception class hierarchy changes:
    assert not issubclass(TemplateAlreadyExistsError, IntegrityError)


async def test_flush_time_duplicate_race_maps_to_already_exists(db, monkeypatch):
    """Concurrent-writer race: pre-check clean, flush collides, reconciliation
    read finds the row → classify as TemplateAlreadyExistsError.

    Simulates the sequence without real concurrency by monkeypatching
    ``get_template_by_key`` to return None (pre-check) then the existing row
    (reconciliation), and making ``db.flush`` raise IntegrityError. Verifies
    both the domain error and that reconciliation actually ran.
    """
    from unittest.mock import AsyncMock

    from sqlalchemy.exc import IntegrityError

    from src.db.models import AgentTemplate
    from src.services.template_service import (
        TemplateAlreadyExistsError,
        TemplateService,
    )

    svc = TemplateService(db)

    # The "row the concurrent writer inserted" — reconciliation finds it.
    concurrent_row = AgentTemplate(
        template_id=12345,
        template_key="swap_executor_v1",
        template_version="swap_executor_v1",
        description="inserted by a concurrent writer",
        allowed_fields_json="[]",
        default_config_json="{}",
        system_prompt="x",
    )

    # 1st call (pre-check) → None. 2nd call (reconciliation) → existing row.
    get_mock = AsyncMock(side_effect=[None, concurrent_row])
    monkeypatch.setattr(svc, "get_template_by_key", get_mock)

    # flush raises IntegrityError (unique-index collision at the DB layer).
    async def _flush_raises():
        raise IntegrityError(
            "UNIQUE constraint failed: agent_templates.template_key",
            {},
            Exception("unique"),
        )

    monkeypatch.setattr(svc.db, "flush", _flush_raises)
    # rollback is called in the except block; stub it so the test stays pure.
    monkeypatch.setattr(svc.db, "rollback", AsyncMock())

    with pytest.raises(TemplateAlreadyExistsError):
        await svc.register_template(**_valid_register_kwargs())

    # Reconciliation must have actually happened (pre-check + post-flush read).
    assert get_mock.await_count == 2

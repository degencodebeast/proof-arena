"""Task 5 — RED tests for FlagshipService (canonical agent reservation).

Covers the edge-case spec at ``.taskmaster/docs/task5-edge-case-spec.md``
N1–N12:

- N1  missing template → FlagshipServiceError
- N2  first bootstrap creates canonical agent + links template FK
- N3  canonical agent shape (subject_type, submission_type, etc.)
- N4  submission_hash is deterministic (sha256 formula)
- N5  bootstrap is idempotent (no duplicate row, same returned agent)
- N6  get_flagship_agent when template missing → None
- N7  get_flagship_agent when template.benchmark_subject_agent_id unset → None
- N8  get_flagship_agent when FK set → returns Agent
- N9  ensure_flagship_exists first call → creates agent
- N10 ensure_flagship_exists second call → returns existing
- N11 agents table has no trust_label column (schema invariant)
- N12 no AgentInstance rows are created by bootstrap

Task 5 / Task 18 boundary discipline is explicit: Task 5 touches only
the `agents` row and the `agent_templates.benchmark_subject_agent_id`
link. No `agent_instances` rows, no trust labels, no hosted-instance
semantics.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger, func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles


os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-t5")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/unused",
)


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kwargs):
    return "INTEGER"


# ---------------------------------------------------------------------
# Fixtures
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


_V2_CONFIG = {
    "allowed_token_universe": [
        "So11111111111111111111111111111111111111112",
        "BRjpCHtyQLNCo8gqRUr8jtdAj5AjPYQaoqbvcZiHok1k",
    ],
    "max_slippage_bps": 100,
    "max_position_size": 1_000_000,
    "max_iterations": 10,
    "max_runtime_seconds": 180,
}

_TEMPLATE_PROMPT = "Balanced swap execution on devnet."


async def _seed_template(
    db: AsyncSession,
    *,
    template_key: str = "swap_executor_v1",
    system_prompt: str = _TEMPLATE_PROMPT,
) -> int:
    from src.db.models import AgentTemplate

    tmpl = AgentTemplate(
        template_key=template_key,
        template_version="swap_executor_v1",
        description="test",
        allowed_fields_json=json.dumps(sorted(_V2_CONFIG.keys())),
        default_config_json=json.dumps(_V2_CONFIG),
        system_prompt=system_prompt,
        is_deployable=1,
    )
    db.add(tmpl)
    await db.flush()
    return tmpl.template_id


def _svc(db: AsyncSession):
    from src.services.flagship_service import FlagshipService

    return FlagshipService(db)


# =====================================================================
# N1 — missing template
# =====================================================================


async def test_bootstrap_missing_template_raises(db):
    from src.services.flagship_service import FlagshipServiceError

    svc = _svc(db)
    with pytest.raises(FlagshipServiceError, match="not found"):
        await svc.bootstrap_flagship(template_key="nonexistent")


# =====================================================================
# N2, N3 — first bootstrap, canonical agent shape
# =====================================================================


async def test_bootstrap_creates_canonical_agent_and_links_template(db):
    from src.db.models import Agent, AgentTemplate

    tid = await _seed_template(db)
    svc = _svc(db)

    agent = await svc.bootstrap_flagship(template_key="swap_executor_v1")

    # Agent row shape
    assert agent.agent_id is not None
    assert agent.privy_user_id == "platform-authority"
    assert agent.display_name == "Flagship Swap Executor"
    assert agent.subject_type == "canonical_template"
    assert agent.submission_type == "canonical_template"
    assert agent.system_prompt == _TEMPLATE_PROMPT
    assert json.loads(agent.config_json) == _V2_CONFIG
    assert agent.status == "active"
    assert agent.moderation_status == "active"

    # Template FK linked
    reread = (
        await db.execute(
            select(AgentTemplate).where(AgentTemplate.template_id == tid)
        )
    ).scalar_one()
    assert reread.benchmark_subject_agent_id == agent.agent_id


# =====================================================================
# N4 — submission_hash is deterministic (sha256 formula)
# =====================================================================


async def test_submission_hash_is_deterministic(db):
    await _seed_template(db)
    svc = _svc(db)
    agent = await svc.bootstrap_flagship(template_key="swap_executor_v1")

    expected = hashlib.sha256(
        b"canonical-template:swap_executor_v1"
    ).hexdigest()
    assert agent.submission_hash == expected


# =====================================================================
# N5 — idempotent on repeat bootstrap
# =====================================================================


async def test_bootstrap_is_idempotent(db):
    from src.db.models import Agent, AgentTemplate

    tid = await _seed_template(db)
    svc = _svc(db)

    first = await svc.bootstrap_flagship(template_key="swap_executor_v1")
    first_id = first.agent_id

    # Count agents before the second call.
    count_before = (
        await db.execute(select(func.count()).select_from(Agent))
    ).scalar_one()

    second = await svc.bootstrap_flagship(template_key="swap_executor_v1")

    count_after = (
        await db.execute(select(func.count()).select_from(Agent))
    ).scalar_one()

    assert second.agent_id == first_id
    assert count_before == count_after  # no duplicate row

    # Template FK still points at the original agent.
    tmpl = (
        await db.execute(
            select(AgentTemplate).where(AgentTemplate.template_id == tid)
        )
    ).scalar_one()
    assert tmpl.benchmark_subject_agent_id == first_id


# =====================================================================
# N6, N7, N8 — get_flagship_agent behavior
# =====================================================================


async def test_get_flagship_agent_missing_template_returns_none(db):
    svc = _svc(db)
    assert await svc.get_flagship_agent(template_key="nonexistent") is None


async def test_get_flagship_agent_unset_fk_returns_none(db):
    await _seed_template(db)
    svc = _svc(db)
    # Template exists but benchmark_subject_agent_id is unset.
    assert await svc.get_flagship_agent(template_key="swap_executor_v1") is None


async def test_get_flagship_agent_with_fk_returns_agent(db):
    await _seed_template(db)
    svc = _svc(db)

    created = await svc.bootstrap_flagship(template_key="swap_executor_v1")
    got = await svc.get_flagship_agent(template_key="swap_executor_v1")
    assert got is not None
    assert got.agent_id == created.agent_id


# =====================================================================
# N9, N10 — ensure_flagship_exists get-or-create
# =====================================================================


async def test_ensure_flagship_exists_creates_when_missing(db):
    from src.db.models import Agent

    await _seed_template(db)
    svc = _svc(db)

    count_before = (
        await db.execute(select(func.count()).select_from(Agent))
    ).scalar_one()

    agent = await svc.ensure_flagship_exists(template_key="swap_executor_v1")

    count_after = (
        await db.execute(select(func.count()).select_from(Agent))
    ).scalar_one()

    assert agent.agent_id is not None
    assert count_after == count_before + 1


async def test_ensure_flagship_exists_is_idempotent(db):
    from src.db.models import Agent

    await _seed_template(db)
    svc = _svc(db)

    first = await svc.ensure_flagship_exists(template_key="swap_executor_v1")

    count_before = (
        await db.execute(select(func.count()).select_from(Agent))
    ).scalar_one()
    second = await svc.ensure_flagship_exists(template_key="swap_executor_v1")
    count_after = (
        await db.execute(select(func.count()).select_from(Agent))
    ).scalar_one()

    assert second.agent_id == first.agent_id
    assert count_before == count_after


# =====================================================================
# N11 — agents has no trust_label column (schema invariant)
# =====================================================================


def test_agents_table_has_no_trust_label_column():
    """Trust labels belong to agent_instances.trust_label per plan §3.
    Task 5 must not introduce or rely on a `trust_label` column on
    `agents`."""
    from src.db.models import Agent

    assert "trust_label" not in {c.name for c in Agent.__table__.columns}


# =====================================================================
# N12 — no AgentInstance rows written
# =====================================================================


async def test_bootstrap_does_not_touch_agent_instances(db):
    from src.db.models import AgentInstance

    await _seed_template(db)
    svc = _svc(db)

    count_before = (
        await db.execute(select(func.count()).select_from(AgentInstance))
    ).scalar_one()
    await svc.bootstrap_flagship(template_key="swap_executor_v1")
    count_after = (
        await db.execute(select(func.count()).select_from(AgentInstance))
    ).scalar_one()

    assert count_before == count_after == 0


# =====================================================================
# Service export — import surface
# =====================================================================


def test_flagship_service_exported_from_services_package():
    import src.services as services_pkg

    assert hasattr(services_pkg, "FlagshipService")
    assert hasattr(services_pkg, "FlagshipServiceError")


# =====================================================================
# CLI --dry-run contract — bootstrap_flagship.py
# =====================================================================


async def test_dry_run_when_flagship_exists_prints_exists_and_does_not_mutate(
    db, capsys
):
    from src.db.models import Agent
    from scripts.bootstrap_flagship import _bootstrap_once

    await _seed_template(db)
    # Pre-create the flagship via the normal path.
    created = await _svc(db).bootstrap_flagship(template_key="swap_executor_v1")

    count_before = (
        await db.execute(select(func.count()).select_from(Agent))
    ).scalar_one()

    rc = await _bootstrap_once(db, template_key="swap_executor_v1", dry_run=True)

    count_after = (
        await db.execute(select(func.count()).select_from(Agent))
    ).scalar_one()

    assert rc == 0
    assert count_after == count_before  # no mutation
    out = capsys.readouterr().out
    assert "[dry-run]" in out
    assert "already exists" in out
    assert f"agent_id={created.agent_id}" in out


async def test_dry_run_when_flagship_missing_prints_would_create_and_does_not_mutate(
    db, capsys
):
    from src.db.models import Agent
    from scripts.bootstrap_flagship import _bootstrap_once

    await _seed_template(db)

    count_before = (
        await db.execute(select(func.count()).select_from(Agent))
    ).scalar_one()

    rc = await _bootstrap_once(db, template_key="swap_executor_v1", dry_run=True)

    count_after = (
        await db.execute(select(func.count()).select_from(Agent))
    ).scalar_one()

    assert rc == 0
    assert count_after == count_before  # no mutation — proves dry-run is real
    out = capsys.readouterr().out
    assert "[dry-run]" in out
    assert "would bootstrap" in out
    assert "swap_executor_v1" in out


async def test_dry_run_when_template_missing_returns_nonzero(db, capsys):
    from scripts.bootstrap_flagship import _bootstrap_once

    rc = await _bootstrap_once(db, template_key="no_such_template", dry_run=True)

    assert rc == 1
    err = capsys.readouterr().err
    assert "not found" in err


async def test_non_dry_run_creates_and_commits(db, capsys):
    from src.db.models import Agent
    from scripts.bootstrap_flagship import _bootstrap_once

    await _seed_template(db)

    rc = await _bootstrap_once(
        db, template_key="swap_executor_v1", dry_run=False
    )

    assert rc == 0
    rows = (
        await db.execute(
            select(Agent).where(Agent.privy_user_id == "platform-authority")
        )
    ).scalars().all()
    assert len(rows) == 1
    out = capsys.readouterr().out
    assert "flagship agent_id=" in out
    assert "[dry-run]" not in out

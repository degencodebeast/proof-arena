"""V2 Phase P0 RED tests — schema lock.

Targets:
- new tables agent_templates and agent_instances
- new columns agents.subject_type and rank_snapshots.subject_type
- provider-agnostic field naming on agent_instances (I4)
- consent_artifact FK (I8)
- self-referential supersedes FK for instance versioning (D4)
- alembic migration upgrade/downgrade/upgrade (D1, E2)

SQLite is used for model-shape tests (fast). Migration up/down cycle is
tested against real Postgres inside Docker in the validation phase — SQLite
batch-mode semantics are not the point of these tests.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger, inspect
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles


os.environ["ADMIN_API_KEY"] = "test-admin-key-p0"
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/unused"
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


# ===========================================================================
# agent_templates
# ===========================================================================


@pytest.mark.asyncio
async def test_agent_templates_table_exists(engine):
    async with engine.connect() as conn:
        tables = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_table_names()
        )
    assert "agent_templates" in tables


@pytest.mark.asyncio
async def test_agent_templates_has_required_columns(engine):
    async with engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sync_conn: {
                c["name"] for c in inspect(sync_conn).get_columns("agent_templates")
            }
        )
    expected = {
        "template_id",
        "template_key",
        "template_version",
        "description",
        "allowed_fields_json",
        "default_config_json",
        "system_prompt",
        "benchmark_subject_agent_id",
        "is_deployable",
        "created_at",
    }
    missing = expected - columns
    assert not missing, f"agent_templates missing columns: {missing}"


@pytest.mark.asyncio
async def test_agent_templates_template_key_is_unique(db: AsyncSession):
    from src.db.models import AgentTemplate

    db.add(AgentTemplate(
        template_key="swap_executor_v1",
        template_version="1",
        description="test",
        allowed_fields_json="[]",
        default_config_json="{}",
        system_prompt="test",
        is_deployable=True,
    ))
    await db.commit()

    db.add(AgentTemplate(
        template_key="swap_executor_v1",  # duplicate
        template_version="1",
        description="dup",
        allowed_fields_json="[]",
        default_config_json="{}",
        system_prompt="dup",
        is_deployable=True,
    ))
    with pytest.raises(Exception):
        await db.commit()


# ===========================================================================
# agent_instances — provider-agnostic field names (I4) + FKs (I8, D3, D4)
# ===========================================================================


@pytest.mark.asyncio
async def test_agent_instances_table_exists(engine):
    async with engine.connect() as conn:
        tables = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_table_names()
        )
    assert "agent_instances" in tables


@pytest.mark.asyncio
async def test_agent_instances_uses_provider_agnostic_field_names(engine):
    """I4 — no Privy-specific field names leak into the schema before validation."""
    async with engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sync_conn: {
                c["name"] for c in inspect(sync_conn).get_columns("agent_instances")
            }
        )
    # Required provider-agnostic names.
    required = {
        "instance_id",
        "template_id",
        "template_version_at_deploy",
        "instance_owner_ref",
        "effective_config_json",
        "consent_artifact_id",
        "runtime_handle_json",
        "wallet_address",
        "hosted_wallet_ref",
        "wallet_provider",
        "trust_label",
        "status",
        "created_at",
        "superseded_by_instance_id",
    }
    missing = required - columns
    assert not missing, f"agent_instances missing columns: {missing}"

    # Forbidden provider-specific names.
    forbidden = {"privy_user_id", "privy_wallet_id", "privy_wallet_ref", "agentos_handle"}
    leaked = forbidden & columns
    assert not leaked, f"agent_instances leaks provider-specific columns: {leaked}"


@pytest.mark.asyncio
async def test_agent_instances_has_consent_artifact_fk(engine):
    """I8 — consent binding surface exists at the DB level even though the
    deploy-time population orchestration is Phase B work."""
    async with engine.connect() as conn:
        fks = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_foreign_keys("agent_instances")
        )
    fk_cols = {tuple(sorted(fk["constrained_columns"])) for fk in fks}
    assert ("consent_artifact_id",) in fk_cols, (
        f"consent_artifact_id FK missing from agent_instances. Got FKs: {fks}"
    )


@pytest.mark.asyncio
async def test_agent_instances_template_fk_points_to_templates(engine):
    """D3 — FK ordering: agent_instances.template_id → agent_templates.template_id."""
    async with engine.connect() as conn:
        fks = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_foreign_keys("agent_instances")
        )
    template_fks = [fk for fk in fks if fk["constrained_columns"] == ["template_id"]]
    assert template_fks, "No FK on template_id"
    assert template_fks[0]["referred_table"] == "agent_templates"


@pytest.mark.asyncio
async def test_agent_instances_supersedes_self_ref(engine):
    """D4 — superseded_by_instance_id is a nullable self-referential FK."""
    async with engine.connect() as conn:
        fks = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_foreign_keys("agent_instances")
        )
    self_fks = [
        fk for fk in fks
        if fk["constrained_columns"] == ["superseded_by_instance_id"]
    ]
    assert self_fks, "superseded_by_instance_id FK missing"
    assert self_fks[0]["referred_table"] == "agent_instances"


# ===========================================================================
# subject_type on agents and rank_snapshots (I5)
# ===========================================================================


@pytest.mark.asyncio
async def test_agents_has_subject_type_column(engine):
    async with engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sync_conn: {
                c["name"] for c in inspect(sync_conn).get_columns("agents")
            }
        )
    assert "subject_type" in columns


@pytest.mark.asyncio
async def test_rank_snapshots_has_subject_type_column(engine):
    async with engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sync_conn: {
                c["name"] for c in inspect(sync_conn).get_columns("rank_snapshots")
            }
        )
    assert "subject_type" in columns


@pytest.mark.asyncio
async def test_new_agent_defaults_to_canonical_template(db: AsyncSession):
    """New rows default to canonical_template so existing code paths that
    don't explicitly set subject_type remain functional."""
    import hashlib

    from src.db.models import Agent

    sh = hashlib.sha256(b"p0test").hexdigest()
    a = Agent(
        privy_user_id="p0-user",
        owner_wallet="Wa" + "1" * 42,
        display_name="P0Test",
        submission_hash=sh,
        system_prompt="prompt",
        config_json="{}",
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    assert a.subject_type == "canonical_template"


# ===========================================================================
# Migration file exists (E2 idempotency is exercised by the Docker/Postgres
# validation step below; here we just check the file exists and has upgrade+downgrade)
# ===========================================================================


def test_p0_migration_file_present():
    """A new Alembic migration adds the P0 schema.

    Naming convention from existing migrations: `<hex>_<slug>.py` under
    backend/alembic/versions/.
    """
    import glob
    from pathlib import Path

    here = Path(__file__).parent.parent
    versions = list(here.glob("alembic/versions/*v2_p0*.py"))
    assert versions, (
        f"No V2 P0 migration found under {here}/alembic/versions/. "
        f"Expected a file matching *v2_p0*.py."
    )

    # Must define both upgrade() and downgrade() — the closeout checklist
    # expects the migration to be reversible.
    text = versions[0].read_text()
    assert "def upgrade() -> None" in text or "def upgrade():" in text
    assert "def downgrade() -> None" in text or "def downgrade():" in text

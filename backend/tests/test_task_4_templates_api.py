"""Task 4 — RED tests for the public template catalog API.

Covers `.taskmaster/docs/task4-edge-case-spec.md` §7 (E1-E11). Uses the
Task 20 / Task 14 TestClient + `app.dependency_overrides` pattern with
save/restore sentinel so sibling modules' overrides are not clobbered.

Task 4 is a public read endpoint — no auth token required. No mutation
endpoints.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator

# Task 4 does NOT use admin or user auth — public read-only endpoints.
# setdefault only so tests that are loaded alongside Task 14 still find
# something; never mutate settings.ADMIN_API_KEY (would clobber Task 14).
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-unused")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/unused",
)

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles

from src.db.engine import get_db
from src.main import app


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kwargs):
    return "INTEGER"


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest_asyncio.fixture
async def test_engine():
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
async def test_session_factory(test_engine):
    return async_sessionmaker(test_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def client(test_session_factory):
    async def _override_db():
        async with test_session_factory() as session:
            yield session

    sentinel = object()
    prev = app.dependency_overrides.get(get_db, sentinel)
    app.dependency_overrides[get_db] = _override_db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        if prev is sentinel:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = prev


@pytest_asyncio.fixture
async def db(test_session_factory) -> AsyncGenerator[AsyncSession, None]:
    async with test_session_factory() as session:
        yield session


# ---------------------------------------------------------------------
# V2 5-field envelope — used by seed helpers to satisfy
# TemplateService envelope validation via register_template.
# ---------------------------------------------------------------------


_V2_ENVELOPE_FIELDS = [
    "allowed_token_universe",
    "max_iterations",
    "max_position_size",
    "max_runtime_seconds",
    "max_slippage_bps",
]

_VALID_DEFAULT_CONFIG = {
    "allowed_token_universe": [
        "So11111111111111111111111111111111111111112",
        "BRjpCHtyQLNCo8gqRUr8jtdAj5AjPYQaoqbvcZiHok1k",
    ],
    "max_slippage_bps": 100,
    "max_position_size": 1_000_000,
    "max_iterations": 10,
    "max_runtime_seconds": 180,
}


# ---------------------------------------------------------------------
# Seed helpers — direct model inserts (bypass service validation so we
# can seed signpost / minimal-config templates for specific test shapes).
# ---------------------------------------------------------------------


async def _seed_template_row(
    db: AsyncSession,
    *,
    template_key: str,
    template_version: str = "v1",
    description: str = "seeded",
    is_deployable: bool = True,
    benchmark_subject_agent_id: int | None = None,
    allowed_fields: list[str] | None = None,
    default_config: dict | None = None,
    system_prompt: str = "be a benchmark agent",
):
    from src.db.models import AgentTemplate

    tmpl = AgentTemplate(
        template_key=template_key,
        template_version=template_version,
        description=description,
        allowed_fields_json=json.dumps(
            sorted(allowed_fields if allowed_fields is not None else _V2_ENVELOPE_FIELDS)
        ),
        default_config_json=json.dumps(
            default_config if default_config is not None else _VALID_DEFAULT_CONFIG
        ),
        system_prompt=system_prompt,
        is_deployable=1 if is_deployable else 0,
        benchmark_subject_agent_id=benchmark_subject_agent_id,
    )
    db.add(tmpl)
    await db.commit()
    await db.refresh(tmpl)
    return tmpl


async def _seed_flagship_agent_and_instance(
    db: AsyncSession,
    *,
    template_id: int,
    trust_label: str = "benchmarked_canonical_template",
    status: str = "live",
):
    """Seed a minimal flagship Agent + AgentInstance for a template so
    `get_template_with_flagship_info` can surface the trust label."""
    from src.db.models import Agent, AgentInstance

    agent = Agent(
        privy_user_id=f"platform-flagship-t{template_id}",
        owner_wallet="sol-platform-owner",
        display_name="flagship-test",
        submission_type="canonical_template",
        submission_hash="f" * 64,
        system_prompt="x",
        config_json="{}",
        provider_type="local",
        subject_type="canonical_template",
        status="active",
        moderation_status="active",
    )
    db.add(agent)
    await db.flush()

    instance = AgentInstance(
        template_id=template_id,
        template_version_at_deploy="v1",
        instance_owner_ref=f"platform-flagship-t{template_id}",
        effective_config_json=json.dumps(_VALID_DEFAULT_CONFIG, sort_keys=True),
        wallet_address="sol-flagship-addr",
        hosted_wallet_ref="flagship-w-id",
        wallet_provider="privy",
        trust_label=trust_label,
        status=status,
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)

    # Wire back-reference from template to canonical flagship agent
    # (required for get_template_with_flagship_info to do the lookup).
    from src.db.models import AgentTemplate

    template = await db.get(AgentTemplate, template_id)
    if template is not None:
        template.benchmark_subject_agent_id = agent.agent_id
        await db.commit()

    return agent, instance


# =====================================================================
# E1 — empty catalog → []
# =====================================================================


async def test_empty_catalog_returns_empty_list(client):
    r = client.get("/api/v1/templates")
    assert r.status_code == 200
    assert r.json() == []


# =====================================================================
# E2 — catalog includes deployable + signpost
# =====================================================================


async def test_catalog_includes_deployable_and_signpost(client, db):
    await _seed_template_row(db, template_key="swap_executor_v1", is_deployable=True)
    await _seed_template_row(
        db, template_key="rebalance_executor_v1", is_deployable=False,
    )

    r = client.get("/api/v1/templates")
    assert r.status_code == 200
    body = r.json()
    keys_to_deployable = {row["template_key"]: row["is_deployable"] for row in body}
    assert keys_to_deployable == {
        "swap_executor_v1": True,
        "rebalance_executor_v1": False,
    }


# =====================================================================
# E3 — catalog ordered newest first
# =====================================================================


async def test_catalog_ordered_newest_first(client, db):
    # Seeded in order: older → newer. Response must be newer → older.
    await _seed_template_row(db, template_key="first_template")
    await _seed_template_row(db, template_key="second_template")
    await _seed_template_row(db, template_key="third_template")

    r = client.get("/api/v1/templates")
    keys = [row["template_key"] for row in r.json()]
    # Service orders by (created_at DESC, template_id DESC). If created_at
    # ties (same tick), template_id DESC resolves — third was inserted
    # last, so it has the highest template_id and appears first.
    assert keys[0] == "third_template"
    assert keys[-1] == "first_template"


# =====================================================================
# E4 — catalog summary shape exact (no raw JSON, no system_prompt)
# =====================================================================


async def test_catalog_summary_shape(client, db):
    await _seed_template_row(db, template_key="summary_shape_t")

    r = client.get("/api/v1/templates")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    row = body[0]

    # Exactly the five summary keys.
    assert set(row.keys()) == {
        "template_key",
        "template_version",
        "description",
        "is_deployable",
        "created_at",
    }
    # No raw JSON blobs, no system_prompt, no allowed_fields, no default_config.
    for forbidden in (
        "allowed_fields_json",
        "default_config_json",
        "system_prompt",
        "allowed_fields",
        "default_config",
        "benchmark_subject_agent_id",
        "flagship_trust_label",
        "template_id",
    ):
        assert forbidden not in row, f"catalog summary leaked {forbidden!r}"


# =====================================================================
# E5 — detail happy path — template exists, no flagship instance
# =====================================================================


async def test_detail_existing_template_no_flagship(client, db):
    await _seed_template_row(db, template_key="swap_executor_v1")

    r = client.get("/api/v1/templates/swap_executor_v1")
    assert r.status_code == 200
    body = r.json()

    assert body["template_key"] == "swap_executor_v1"
    assert body["template_version"] == "v1"
    assert body["is_deployable"] is True
    # No flagship instance seeded → trust label is None.
    assert body["flagship_trust_label"] is None
    # Parsed structured fields (not raw JSON).
    assert isinstance(body["allowed_fields"], list)
    assert isinstance(body["default_config"], dict)
    # system_prompt IS public on canonical templates (published spec).
    assert body["system_prompt"] == "be a benchmark agent"


# =====================================================================
# E6 — detail 404 on unknown key
# =====================================================================


async def test_detail_404_for_unknown_key(client):
    r = client.get("/api/v1/templates/does_not_exist")
    assert r.status_code == 404
    assert r.json()["detail"] == "Template not found"


# =====================================================================
# E7 — detail surfaces live flagship trust label
# =====================================================================


async def test_detail_surfaces_live_flagship_trust_label(client, db):
    tmpl = await _seed_template_row(db, template_key="swap_executor_v1")
    await _seed_flagship_agent_and_instance(
        db,
        template_id=tmpl.template_id,
        trust_label="benchmarked_canonical_template",
        status="live",
    )

    r = client.get("/api/v1/templates/swap_executor_v1")
    assert r.status_code == 200
    assert r.json()["flagship_trust_label"] == "benchmarked_canonical_template"


# =====================================================================
# E8 — detail ignores non-flagship trust labels
# =====================================================================


async def test_detail_ignores_non_flagship_trust_labels(client, db):
    tmpl = await _seed_template_row(db, template_key="swap_executor_v1")
    # A customized-instance deployment against the same template does
    # NOT promote to flagship.
    await _seed_flagship_agent_and_instance(
        db,
        template_id=tmpl.template_id,
        trust_label="benchmark_compatible_customized_instance",
        status="live",
    )

    r = client.get("/api/v1/templates/swap_executor_v1")
    assert r.status_code == 200
    # flagship_trust_label must remain None — only the reserved
    # canonical-template label counts.
    assert r.json()["flagship_trust_label"] is None


# =====================================================================
# E9 — public, no auth required
# =====================================================================


async def test_public_no_auth_required(client, db):
    await _seed_template_row(db, template_key="swap_executor_v1")

    # Both endpoints without any Authorization header → 200.
    r_list = client.get("/api/v1/templates")
    assert r_list.status_code == 200
    r_detail = client.get("/api/v1/templates/swap_executor_v1")
    assert r_detail.status_code == 200


# =====================================================================
# E10 — raw JSON strings never leaked
# =====================================================================


async def test_raw_json_fields_not_leaked(client, db):
    await _seed_template_row(db, template_key="swap_executor_v1")

    r_detail = client.get("/api/v1/templates/swap_executor_v1")
    body = r_detail.json()
    assert "allowed_fields_json" not in body
    assert "default_config_json" not in body


# =====================================================================
# E11 — detail allowed_fields parsed and matches V2 envelope
# =====================================================================


async def test_detail_allowed_fields_is_parsed_envelope(client, db):
    await _seed_template_row(db, template_key="swap_executor_v1")

    r = client.get("/api/v1/templates/swap_executor_v1")
    assert r.status_code == 200
    allowed = r.json()["allowed_fields"]

    # Parsed list, sorted, exactly the 5 V2 envelope fields.
    assert allowed == sorted(_V2_ENVELOPE_FIELDS)

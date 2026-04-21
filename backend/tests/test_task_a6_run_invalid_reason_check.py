"""Task 1 / A-6 — RED tests for the runs.invalid_reason CHECK constraint.

These tests declare the CHECK contract at the SQLAlchemy model layer so the
in-memory SQLite engine used in the rest of the backend test suite also
enforces the constraint. The equivalent Postgres-side CHECK ships in the
Alembic migration for this task.

See .taskmaster/docs/task1-edge-case-spec.md.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles


os.environ["ADMIN_API_KEY"] = "test-admin-key-a6-check"
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


async def _insert_prereqs(db: AsyncSession) -> tuple[int, int]:
    """Seed one Agent + one Challenge so Runs FK-constrain cleanly."""
    from src.db.models import Agent, Challenge

    agent = Agent(
        privy_user_id="u",
        owner_wallet="w" * 44,
        display_name="t",
        submission_hash="a" * 64,
        system_prompt="x",
    )
    db.add(agent)

    challenge = Challenge(
        llm_provider="anthropic",
        llm_model="claude-3-5-sonnet-20241022",
        config_json="{}",
    )
    db.add(challenge)
    await db.flush()
    return agent.agent_id, challenge.challenge_id


async def _insert_run(
    db: AsyncSession, invalid_reason: str | None
) -> None:
    from src.db.models import Run

    agent_id, challenge_id = await _insert_prereqs(db)
    run = Run(
        challenge_id=challenge_id,
        agent_id=agent_id,
        provider_type="local",
        status="completed",
        completion_status="invalid" if invalid_reason else "complete",
        invalid_reason=invalid_reason,
        onchain_address="r" * 44,
    )
    db.add(run)
    await db.flush()


# Test 8 ---------------------------------------------------------------


async def test_check_rejects_off_contract_invalid_reason(db):
    """Inserting an off-contract invalid_reason must raise IntegrityError."""
    with pytest.raises(IntegrityError):
        await _insert_run(db, invalid_reason="bogus_value_not_in_enum")


# Test 9 ---------------------------------------------------------------


async def test_null_invalid_reason_accepted(db):
    """NULL invalid_reason must still be accepted (nullable column preserved)."""
    await _insert_run(db, invalid_reason=None)


# Test 10 --------------------------------------------------------------


async def test_all_enum_values_valid_for_check(db):
    """Every RunInvalidReason enum value must pass the CHECK.

    Seeds one distinct (agent, challenge) pair per value to avoid the
    `uq_runs_challenge_agent` unique index firing before the CHECK.
    """
    from src.db.models import Agent, Challenge, Run
    from src.integrity.failure_taxonomy import RunInvalidReason

    for idx, reason in enumerate(RunInvalidReason):
        agent = Agent(
            privy_user_id=f"u{idx}",
            owner_wallet=("w" * 43 + str(idx))[-44:],
            display_name=f"t{idx}",
            submission_hash=str(idx).rjust(64, "a"),
            system_prompt="x",
        )
        challenge = Challenge(
            llm_provider="anthropic",
            llm_model="claude-3-5-sonnet-20241022",
            config_json="{}",
        )
        db.add_all([agent, challenge])
        await db.flush()
        db.add(
            Run(
                challenge_id=challenge.challenge_id,
                agent_id=agent.agent_id,
                status="completed",
                completion_status="invalid",
                invalid_reason=reason.value,
            )
        )
    # If any enum value violates the CHECK, this flush raises IntegrityError.
    await db.flush()

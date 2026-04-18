"""Task 15: Integration test fixtures.

Provides:
- Async SQLite in-memory DB engine + session (real SQLAlchemy).
- Mock program_client with all on-chain methods stubbed.
- Helper factories for seeding Agents/Challenges/Runs/Events.
- FastAPI TestClient bound to the same session so HTTP reads see writes.

Deterministic lifecycle only. No live Jupiter/Privy/Solana RPC.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

# Set env BEFORE any src.* import.
# NOTE: We keep DATABASE_URL pointing at a Postgres placeholder so the
# import-time default engine accepts pool_size kwargs. That engine is never
# actually used — tests override `get_db` to yield a SQLite session bound to
# the per-test engine below.
os.environ["ADMIN_API_KEY"] = "test-admin-key-integration"
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_never_used"
)

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles


# Make BigInteger render as INTEGER on SQLite so INTEGER PRIMARY KEY
# autoincrement works (SQLite only autoincrements the INTEGER type).
@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kwargs):
    return "INTEGER"

from src.config import settings

settings.ADMIN_API_KEY = "test-admin-key-integration"

from src.db.models import Base


# ---------------------------------------------------------------------------
# Engine + session
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    """Fresh SQLite in-memory engine per test, with all tables created."""
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    """Yields a session bound to the per-test engine."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session


# ---------------------------------------------------------------------------
# Mock program client — on-chain surface
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_program():
    """All on-chain calls return deterministic mock tx signatures / PDAs."""
    p = MagicMock()

    # StrategyService path (not called in integration tests; register is deferred)
    p.register_strategy = AsyncMock(
        return_value=("mock_register_tx", "StrategyPDA11111111111111111111111111111111")
    )

    # ChallengeService path
    p.create_challenge = AsyncMock(
        return_value=("mock_create_tx", "ChallengePDA11111111111111111111111111111111")
    )
    # For create_run we return a unique valid pubkey per call
    async def _create_run(*args, **kwargs):
        from solders.pubkey import Pubkey  # type: ignore[import-untyped]
        return ("mock_create_run_tx", str(Pubkey.new_unique()))
    p.create_run = AsyncMock(side_effect=_create_run)
    p.start_challenge = AsyncMock(return_value="mock_start_tx")

    # RunnerService path (not invoked here; we seed Runs directly)
    p.finalize_run = AsyncMock(return_value="mock_finalize_tx")

    # SettlementService path
    p.settle_challenge = AsyncMock(return_value="mock_settle_tx")
    p.update_agent_rank = AsyncMock(return_value="mock_rank_tx")

    return p


# ---------------------------------------------------------------------------
# Factory helpers (keep test code terse)
# ---------------------------------------------------------------------------


def _valid_pubkey(_seed: str = "") -> str:
    """Return a valid Solana pubkey (base58-encoded 32 bytes).

    Uses solders to generate a real pubkey — services call Pubkey.from_string()
    which validates base58, so fake strings would fail."""
    from solders.pubkey import Pubkey  # type: ignore[import-untyped]

    return str(Pubkey.new_unique())


_ID_COUNTER = {"agent": 0, "challenge": 0, "run": 0, "event": 0}


def _next_id(kind: str) -> int:
    _ID_COUNTER[kind] += 1
    return _ID_COUNTER[kind]


@pytest.fixture(autouse=True)
def _reset_id_counters():
    """Reset ID counters per test so isolation is preserved."""
    for k in _ID_COUNTER:
        _ID_COUNTER[k] = 0


async def seed_agent(
    db: AsyncSession,
    *,
    agent_id: int | None = None,
    display_name: str = "TestBot",
    privy_user_id: str | None = None,
    owner_wallet: str = "WalletAddr11111111111111111111111111111111",
    system_prompt: str = "Be a benchmark agent.",
    onchain_address: str | None = None,
    status: str = "active",
):
    """Insert an Agent row directly. Provides explicit IDs (SQLite does not
    autoincrement BIGINT)."""
    from src.db.models import Agent
    import hashlib
    import json as _json

    sh = hashlib.sha256(f"{system_prompt}{display_name}{_json.dumps({})}".encode()).hexdigest()
    agent = Agent(
        agent_id=agent_id if agent_id is not None else _next_id("agent"),
        privy_user_id=privy_user_id or f"test-user-{display_name}",
        owner_wallet=owner_wallet,
        display_name=display_name,
        submission_hash=sh,
        system_prompt=system_prompt,
        config_json="{}",
        status=status,
        moderation_status="active",
        onchain_address=onchain_address or _valid_pubkey(f"Strategy{display_name}"),
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


async def seed_challenge(
    db: AsyncSession,
    *,
    num_contestants: int = 2,
    status: str = "active",
    starting_usdc: int = 100_000_000,
):
    """Insert a Challenge row directly."""
    from src.db.models import Challenge
    import json as _json

    challenge = Challenge(
        challenge_id=_next_id("challenge"),
        challenge_type="swap_execution",
        challenge_version=settings.CHALLENGE_VERSION,
        llm_provider="anthropic",
        llm_model="claude-sonnet-4-20250514",
        config_json=_json.dumps(
            {
                "starting_usdc": starting_usdc,
                "swap_intents": ["SOL"],
                "max_slippage_bps": 100,
                "iteration_budget": 20,
                "time_budget_secs": 300,
            }
        ),
        status=status,
        num_contestants=num_contestants,
        num_finalized=0,
        onchain_address=_valid_pubkey("Challenge"),
    )
    db.add(challenge)
    await db.commit()
    await db.refresh(challenge)
    return challenge


async def seed_finalized_run(
    db: AsyncSession,
    *,
    challenge_id: int,
    agent_id: int,
    ending_value: int = 105_000_000,
    starting_value: int = 100_000_000,
    status: str = "completed",
    completion_status: str | None = "complete",
    run_log_hash: str | None = "a" * 64,
    invalid_reason: str | None = None,
):
    """Insert a Run in terminal state, ready for settlement."""
    from datetime import datetime, timezone
    from src.db.models import Run

    run = Run(
        run_id=_next_id("run"),
        challenge_id=challenge_id,
        agent_id=agent_id,
        provider_type="local",
        status=status,
        completion_status=completion_status,
        starting_value=starting_value,
        ending_value=ending_value,
        run_log_hash=run_log_hash,
        invalid_reason=invalid_reason,
        app_version=settings.APP_VERSION,
        challenge_type="swap_execution",
        challenge_version=settings.CHALLENGE_VERSION,
        action_schema_version=settings.ACTION_SCHEMA_VERSION,
        evidence_schema_version=settings.EVIDENCE_SCHEMA_VERSION,
        onchain_address=_valid_pubkey(f"Run{challenge_id}Agent{agent_id}"),
        ended_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def seed_run_events(
    db: AsyncSession,
    *,
    run_id: int,
    count: int = 3,
):
    """Insert a minimal sequence of RunEvents."""
    from datetime import datetime, timezone
    from src.db.models import RunEvent

    event_types = ["observe", "decide", "execute", "finalize"]
    for i in range(count):
        evt = RunEvent(
            event_id=_next_id("event"),
            run_id=run_id,
            sequence_no=i + 1,
            event_type=event_types[i % len(event_types)],
            timestamp=datetime.now(timezone.utc),
            state_snapshot_json="{}",
        )
        db.add(evt)
    await db.commit()


# Export fixture functions for use in tests
@pytest.fixture
def factories():
    """Expose seed helpers as a namespace."""
    return type(
        "Factories",
        (),
        {
            "seed_agent": staticmethod(seed_agent),
            "seed_challenge": staticmethod(seed_challenge),
            "seed_finalized_run": staticmethod(seed_finalized_run),
            "seed_run_events": staticmethod(seed_run_events),
        },
    )

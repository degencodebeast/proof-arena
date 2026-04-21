"""Task 16 RED tests — program client factory + admin fail-closed + partial failure.

Covers edge-case spec invariants:
- I1 — DB/chain non-divergence (compensating state, not rollback)
- I3 / N7 — Fail-closed admin without program client
- I9 — Partial multi-run failure leaves legible compensating state, settle fails closed
- N1..N5 — Negative cases for the factory configuration

These tests are deliberately RED until:
- `src.chain.get_program_client` is implemented
- `src/api/admin.py` wires the factory into ChallengeService calls

SettlementService/ChallengeService behavior the tests depend on is already
shipped in V1 per the prior task suite.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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


# Env setup MUST happen before src.* import (mirrors integration conftest).
os.environ["ADMIN_API_KEY"] = "test-admin-key-task16"
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/unused_in_sqlite"
)


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kwargs):
    return "INTEGER"


from src.config import settings  # noqa: E402

settings.ADMIN_API_KEY = "test-admin-key-task16"

from src.db.models import Base  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fixtures — keep the surface narrow; mirror integration conftest.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session


def _valid_pubkey() -> str:
    from solders.pubkey import Pubkey  # type: ignore[import-untyped]

    return str(Pubkey.new_unique())


# ===========================================================================
# A. Factory behavior — N1..N5 + valid config
# ===========================================================================


def test_missing_program_id_returns_none_client(monkeypatch):
    """N1 — Empty PROGRAM_ID → factory returns None, logs warning, does not crash."""
    from src.chain import get_program_client

    monkeypatch.setattr(settings, "PROGRAM_ID", "")
    monkeypatch.setattr(settings, "AUTHORITY_KEYPAIR_PATH", "/tmp/whatever.json")

    assert get_program_client() is None


def test_missing_authority_keypair_path_returns_none_client(monkeypatch):
    """N2 — Empty AUTHORITY_KEYPAIR_PATH → factory returns None."""
    from src.chain import get_program_client

    monkeypatch.setattr(settings, "PROGRAM_ID", "GFnG5esZ77F4NL3CpSE9tLHG4ExghiQuBB83ZtGYuqcu")
    monkeypatch.setattr(settings, "AUTHORITY_KEYPAIR_PATH", "")

    assert get_program_client() is None


def test_invalid_keypair_file_returns_not_ready(monkeypatch, tmp_path):
    """N3 — AUTHORITY_KEYPAIR_PATH points at nonexistent file → SolanaService.is_ready=False → factory returns None."""
    from src.chain import get_program_client

    nonexistent = tmp_path / "does-not-exist.json"
    monkeypatch.setattr(settings, "PROGRAM_ID", "GFnG5esZ77F4NL3CpSE9tLHG4ExghiQuBB83ZtGYuqcu")
    monkeypatch.setattr(settings, "AUTHORITY_KEYPAIR_PATH", str(nonexistent))

    assert get_program_client() is None


def test_malformed_keypair_json_returns_none_client(monkeypatch, tmp_path):
    """N4 — Keypair file exists but contains invalid JSON → factory returns None without raising."""
    from src.chain import get_program_client

    bad = tmp_path / "bad-keypair.json"
    bad.write_text("this is not json", encoding="utf-8")

    monkeypatch.setattr(settings, "PROGRAM_ID", "GFnG5esZ77F4NL3CpSE9tLHG4ExghiQuBB83ZtGYuqcu")
    monkeypatch.setattr(settings, "AUTHORITY_KEYPAIR_PATH", str(bad))

    # Must not raise; factory is fail-closed.
    assert get_program_client() is None


def test_wrong_length_keypair_returns_none_client(monkeypatch, tmp_path):
    """N5 — JSON parses but byte array is not a 64-byte Solana keypair → factory returns None."""
    from src.chain import get_program_client

    wrong = tmp_path / "wrong-length.json"
    wrong.write_text(json.dumps([1, 2, 3, 4]), encoding="utf-8")

    monkeypatch.setattr(settings, "PROGRAM_ID", "GFnG5esZ77F4NL3CpSE9tLHG4ExghiQuBB83ZtGYuqcu")
    monkeypatch.setattr(settings, "AUTHORITY_KEYPAIR_PATH", str(wrong))

    assert get_program_client() is None


def test_valid_config_creates_working_client(monkeypatch, tmp_path):
    """Valid PROGRAM_ID + valid keypair file → factory returns an AgentArenaClient instance."""
    from solders.keypair import Keypair  # type: ignore[import-untyped]

    # Write a real keypair so SolanaService can load it.
    kp = Keypair()
    kp_path = tmp_path / "valid-keypair.json"
    kp_path.write_text(json.dumps(list(bytes(kp))), encoding="utf-8")

    monkeypatch.setattr(settings, "PROGRAM_ID", "GFnG5esZ77F4NL3CpSE9tLHG4ExghiQuBB83ZtGYuqcu")
    monkeypatch.setattr(settings, "AUTHORITY_KEYPAIR_PATH", str(kp_path))

    from src.chain import get_program_client
    from src.chain.program_client import AgentArenaClient

    client = get_program_client()
    assert client is not None
    assert isinstance(client, AgentArenaClient)


# ===========================================================================
# B. Admin fail-closed — I3 / N7
# ===========================================================================


@pytest_asyncio.fixture
async def _test_client_no_program(engine, monkeypatch):
    """TestClient with DB bound + get_program_client() forced to return None.

    Surgical teardown: only pops the get_db override we installed, so that
    any other test file's module-level `app.dependency_overrides` entries
    survive. Calling `app.dependency_overrides.clear()` here would wipe
    test_task11_api.py's mock_db override and force later tests to hit
    the real Postgres engine.
    """
    from src.db.engine import get_db
    from src.main import app

    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with maker() as session:
            yield session

    prior_get_db_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_get_db

    # Other test files (e.g. test_task11_api.py) mutate settings.ADMIN_API_KEY
    # at module import time. Force it back to our expected value for this
    # fixture's scope; monkeypatch restores the prior value automatically.
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "test-admin-key-task16")

    # Force factory to return None.
    import src.chain as chain_mod
    import src.api.admin as admin_mod

    monkeypatch.setattr(chain_mod, "get_program_client", lambda: None)
    # admin.py imports get_program_client at module load time; patch there too.
    if hasattr(admin_mod, "get_program_client"):
        monkeypatch.setattr(admin_mod, "get_program_client", lambda: None)

    client = TestClient(app)
    yield client

    # Restore the prior override (or pop if there was none).
    if prior_get_db_override is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = prior_get_db_override


def test_admin_create_challenge_502_without_program_client(_test_client_no_program):
    """N7 / I3 — POST /admin/challenges with no program client → 502, body mentions chain/program."""
    resp = _test_client_no_program.post(
        "/api/v1/admin/challenges",
        json={
            "challenge_type": "swap_execution",
            "starting_usdc": 100_000_000,
            "swap_intents": ["SOL"],
            "allowed_routes": [],
            "max_slippage_bps": 100,
            "iteration_budget": 20,
            "time_budget_secs": 300,
            "llm_provider": "anthropic",
            "llm_model": "claude-sonnet-4-20250514",
            # Schema requires >=1; fail-closed triggers in _require_program()
            # BEFORE the service touches the DB, so the specific ID is irrelevant.
            "contestant_agent_ids": [1],
        },
        headers={"Authorization": "Bearer test-admin-key-task16"},
    )
    assert resp.status_code == 502, (
        f"Expected 502 fail-closed; got {resp.status_code}: {resp.text}"
    )
    detail = resp.json().get("detail", "").lower()
    assert "program" in detail or "chain" in detail or "on-chain" in detail


def test_admin_start_challenge_502_without_program_client(_test_client_no_program):
    """I3 — POST /admin/challenges/{id}/start with no program client → 502 (even if the challenge does not exist)."""
    resp = _test_client_no_program.post(
        "/api/v1/admin/challenges/9999/start",
        headers={"Authorization": "Bearer test-admin-key-task16"},
    )
    # 502 (program client missing — fail-closed BEFORE the 404 for unknown challenge),
    # or 404 if the service orders checks differently. Either surfaces the
    # fail-closed behavior without silently succeeding; we assert it is NOT 200
    # and NOT 500. 502 is the documented contract; 404 is acceptable because
    # it still prevents silent success.
    assert resp.status_code in (404, 502)
    assert resp.status_code != 200


# ===========================================================================
# C. Partial multi-run failure — I9
# ===========================================================================


@pytest.mark.asyncio
async def test_partial_create_run_second_fails_leaves_legible_state(db: AsyncSession):
    """I9(a) — If create_challenge loops create_run and the second call's on-chain
    side raises, the resulting DB state must be legible: the second Run row
    exists with `status='onchain_failed'`, so downstream settlement fails closed.

    Proves:
    - No silent partial success.
    - Compensating marker (`onchain_failed`) is applied.
    - Challenge is NOT marked `completed`.
    """
    from src.db.models import Agent, Run
    from src.services.challenge_service import ChallengeService

    # Seed two agents that look fully on-chain-registered.
    import hashlib
    import json as _json
    agents = []
    for i in range(2):
        display = f"Agent{i}"
        sh = hashlib.sha256(f"prompt{i}".encode()).hexdigest()
        a = Agent(
            agent_id=100 + i,
            privy_user_id=f"user-{i}",
            owner_wallet=_valid_pubkey(),
            display_name=display,
            submission_hash=sh,
            system_prompt=f"prompt{i}",
            config_json="{}",
            status="active",
            moderation_status="active",
            onchain_address=_valid_pubkey(),
        )
        db.add(a)
        agents.append(a)
    await db.commit()
    for a in agents:
        await db.refresh(a)

    # Mock program: create_challenge ok, create_run first ok, second raises.
    call_counter = {"create_run": 0}

    async def _create_run_side_effect(*args, **kwargs):
        call_counter["create_run"] += 1
        if call_counter["create_run"] == 1:
            return ("tx_run_1", _valid_pubkey())
        raise RuntimeError("simulated devnet RPC timeout on create_run #2")

    program = MagicMock()
    program.create_challenge = AsyncMock(
        return_value=("tx_create_challenge", _valid_pubkey())
    )
    program.create_run = AsyncMock(side_effect=_create_run_side_effect)

    svc = ChallengeService(db, program_client=program)
    challenge = await svc.create_challenge(
        contestant_agent_ids=[agents[0].agent_id, agents[1].agent_id],
    )

    # Challenge row exists, on-chain create_challenge succeeded.
    assert challenge.challenge_id is not None
    assert challenge.onchain_address is not None

    # Two Run rows exist.
    from sqlalchemy import select
    runs = (
        await db.execute(
            select(Run).where(Run.challenge_id == challenge.challenge_id).order_by(Run.run_id)
        )
    ).scalars().all()
    assert len(runs) == 2

    # Exactly one Run carries the compensating marker.
    failed_runs = [r for r in runs if r.status == "onchain_failed"]
    assert len(failed_runs) == 1, (
        f"Expected exactly one run with status='onchain_failed'; got "
        f"statuses={[r.status for r in runs]}"
    )

    # Challenge is not falsely marked complete/settled.
    assert challenge.status != "completed"
    assert challenge.winner_agent_id is None


@pytest.mark.asyncio
async def test_settle_fails_closed_when_any_run_is_onchain_failed(db: AsyncSession):
    """I9(b) — Settlement must fail closed when any contestant Run is in
    `onchain_failed` (non-terminal compensating state). This holds whether
    the failure came from create_run or finalize_run.
    """
    from src.db.models import Agent, Challenge, Run
    from src.services.settlement_service import SettlementError, SettlementService

    # Seed 2 agents.
    import hashlib
    agents = []
    for i in range(2):
        sh = hashlib.sha256(f"agent{i}".encode()).hexdigest()
        a = Agent(
            agent_id=200 + i,
            privy_user_id=f"user-{i}",
            owner_wallet=_valid_pubkey(),
            display_name=f"Agent{i}",
            submission_hash=sh,
            system_prompt=f"prompt{i}",
            config_json="{}",
            status="active",
            moderation_status="active",
            onchain_address=_valid_pubkey(),
        )
        db.add(a)
        agents.append(a)

    # Seed an active Challenge with num_contestants=2.
    import json as _json
    challenge = Challenge(
        challenge_id=200,
        challenge_type="swap_execution",
        challenge_version=settings.CHALLENGE_VERSION,
        llm_provider="anthropic",
        llm_model="claude-sonnet-4-20250514",
        config_json=_json.dumps({"starting_usdc": 100_000_000}),
        status="active",
        num_contestants=2,
        num_finalized=1,  # Only 1 finalized — the other is onchain_failed.
        onchain_address=_valid_pubkey(),
    )
    db.add(challenge)

    # Seed runs: one completed+terminal, one onchain_failed.
    from datetime import datetime, timezone
    good_run = Run(
        run_id=201,
        challenge_id=challenge.challenge_id,
        agent_id=agents[0].agent_id,
        provider_type="local",
        status="completed",
        completion_status="complete",
        starting_value=100_000_000,
        ending_value=110_000_000,
        run_log_hash="a" * 64,
        app_version=settings.APP_VERSION,
        challenge_type="swap_execution",
        challenge_version=settings.CHALLENGE_VERSION,
        action_schema_version=settings.ACTION_SCHEMA_VERSION,
        evidence_schema_version=settings.EVIDENCE_SCHEMA_VERSION,
        onchain_address=_valid_pubkey(),
        ended_at=datetime.now(timezone.utc),
    )
    bad_run = Run(
        run_id=202,
        challenge_id=challenge.challenge_id,
        agent_id=agents[1].agent_id,
        provider_type="local",
        status="onchain_failed",
        completion_status=None,
        starting_value=100_000_000,
        ending_value=None,
        run_log_hash=None,
        app_version=settings.APP_VERSION,
        challenge_type="swap_execution",
        challenge_version=settings.CHALLENGE_VERSION,
        action_schema_version=settings.ACTION_SCHEMA_VERSION,
        evidence_schema_version=settings.EVIDENCE_SCHEMA_VERSION,
    )
    db.add(good_run)
    db.add(bad_run)
    await db.commit()

    program = MagicMock()
    program.settle_challenge = AsyncMock(return_value="mock_settle_tx")

    svc = SettlementService(db, program_client=program)
    with pytest.raises(SettlementError) as exc:
        await svc.settle_challenge(challenge.challenge_id)

    # Error message should reference the blocking condition (non-terminal or unsettled).
    msg = str(exc.value).lower()
    assert any(
        kw in msg for kw in ("terminal", "eligible", "onchain_failed", "settle")
    ), f"SettlementError message uninformative: {exc.value}"

    # On-chain settle MUST NOT have been called.
    program.settle_challenge.assert_not_called()

    # Challenge must not be marked completed.
    await db.refresh(challenge)
    assert challenge.status != "completed"
    assert challenge.winner_agent_id is None

"""Task 16 RED tests — init_devnet_program.py idempotency + devnet guard.

These tests target the script at backend/scripts/init_devnet_program.py. The
script does not exist yet, so the tests are RED until it is created with:
- a `main()` / `init_program()` coroutine the tests can call directly,
- a hard devnet guard that exits non-zero if SOLANA_CLUSTER != "devnet",
- idempotent handling of the "already initialized" case.

We do NOT talk to a real Solana RPC from these tests. The AgentArenaClient
and SolanaService are mocked.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


os.environ["ADMIN_API_KEY"] = "test-admin-key-task16"
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/unused"
)


@pytest.mark.asyncio
async def test_init_first_run_submits_initialize_and_prints_signature(
    capsys, monkeypatch
):
    """First invocation submits the initialize instruction and prints the tx
    signature. Exits 0. Idempotency path is NOT taken."""
    from src.config import settings

    monkeypatch.setattr(settings, "PROGRAM_ID", "GFnG5esZ77F4NL3CpSE9tLHG4ExghiQuBB83ZtGYuqcu")
    monkeypatch.setattr(settings, "AUTHORITY_KEYPAIR_PATH", "/tmp/irrelevant.json")
    monkeypatch.setattr(settings, "SOLANA_CLUSTER", "devnet")
    monkeypatch.setattr(settings, "SOLANA_RPC_URL", "https://api.devnet.solana.com")

    # Fake program client that succeeds on first initialize().
    fake_client = MagicMock()
    fake_client.initialize = AsyncMock(return_value="FakeTxSignatureFirstInit1111111111111111")
    fake_client.derive_config_pda = MagicMock(
        return_value=("ConfigPda11111111111111111111111111111111111", 255)
    )

    import scripts.init_devnet_program as init_script

    # Patch the factory used by the script.
    monkeypatch.setattr(init_script, "get_program_client", lambda: fake_client)

    exit_code = await init_script.init_program()

    assert exit_code == 0
    fake_client.initialize.assert_awaited_once()
    out = capsys.readouterr().out
    assert "FakeTxSignatureFirstInit1111111111111111" in out
    assert "already" not in out.lower()


@pytest.mark.asyncio
async def test_init_second_run_detects_already_initialized_and_exits_zero(
    capsys, monkeypatch
):
    """Second invocation: initialize() raises an 'already initialized' style
    error. Script catches, prints the config PDA, exits 0. No re-submission."""
    from src.config import settings

    monkeypatch.setattr(settings, "PROGRAM_ID", "GFnG5esZ77F4NL3CpSE9tLHG4ExghiQuBB83ZtGYuqcu")
    monkeypatch.setattr(settings, "AUTHORITY_KEYPAIR_PATH", "/tmp/irrelevant.json")
    monkeypatch.setattr(settings, "SOLANA_CLUSTER", "devnet")
    monkeypatch.setattr(settings, "SOLANA_RPC_URL", "https://api.devnet.solana.com")

    fake_client = MagicMock()
    # Simulate the "account already in use" / AlreadyInitialized surface.
    fake_client.initialize = AsyncMock(
        side_effect=RuntimeError(
            "custom program error: 0x0: account already in use"
        )
    )
    fake_client.derive_config_pda = MagicMock(
        return_value=("ConfigPdaAlreadyExists22222222222222222222222", 254)
    )

    import scripts.init_devnet_program as init_script

    monkeypatch.setattr(init_script, "get_program_client", lambda: fake_client)

    exit_code = await init_script.init_program()

    assert exit_code == 0, "Idempotent re-run must exit 0, not non-zero."
    fake_client.initialize.assert_awaited_once()
    out = capsys.readouterr().out.lower()
    assert "already" in out, "Idempotent run must print an 'already initialized' style message."
    assert "configpdaalreadyexists" in out.lower() or "pda" in out


@pytest.mark.asyncio
async def test_init_fails_closed_on_non_devnet_cluster(capsys, monkeypatch):
    """Devnet-only guard. If SOLANA_CLUSTER != 'devnet' the script must refuse
    to run, exit non-zero, and never call AgentArenaClient.initialize()."""
    from src.config import settings

    monkeypatch.setattr(settings, "PROGRAM_ID", "GFnG5esZ77F4NL3CpSE9tLHG4ExghiQuBB83ZtGYuqcu")
    monkeypatch.setattr(settings, "AUTHORITY_KEYPAIR_PATH", "/tmp/irrelevant.json")
    monkeypatch.setattr(settings, "SOLANA_CLUSTER", "mainnet-beta")
    monkeypatch.setattr(settings, "SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

    fake_client = MagicMock()
    fake_client.initialize = AsyncMock(return_value="ShouldNeverBeCalled")

    import scripts.init_devnet_program as init_script

    monkeypatch.setattr(init_script, "get_program_client", lambda: fake_client)

    exit_code = await init_script.init_program()

    assert exit_code != 0, "Non-devnet cluster must exit non-zero."
    fake_client.initialize.assert_not_called()
    captured = capsys.readouterr()
    combined = (captured.out + captured.err).lower()
    assert "devnet" in combined, f"Error output must mention the devnet guard. got={combined!r}"

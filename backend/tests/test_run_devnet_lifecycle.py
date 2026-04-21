"""Task 16 RED tests — run_devnet_lifecycle.py orchestration + devnet guard.

Targets backend/scripts/run_devnet_lifecycle.py. These are unit-level guards:
- the real end-to-end proof is a manual devnet run captured in the testing
  report,
- these tests assert the script's call sequence, JSON summary shape, and
  devnet-only guard, independent of real RPC.

Design choice: the script does step 5 (deterministic finalize) and step 6
(settlement) via direct backend service calls, not HTTP. The test therefore
mocks step-level helpers (register_strategy, create_challenge_via_api, ...)
rather than HTTP alone. This keeps the orchestration-sequence assertion
decoupled from transport.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


os.environ["ADMIN_API_KEY"] = "test-admin-key-task16"
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/unused"
)


BACKEND_ROOT = Path(__file__).parent.parent
SCRIPT_PATH = BACKEND_ROOT / "scripts" / "run_devnet_lifecycle.py"


# ---------------------------------------------------------------------------
# Smoke: --help parses without importing heavy state.
# ---------------------------------------------------------------------------


def test_lifecycle_script_help_runs_and_documents_env_vars():
    """--help runs end to end and documents the env vars the script needs.

    Weak on purpose (documentation + import-health check). The orchestration
    sequence test below carries the real load.
    """
    assert SCRIPT_PATH.exists(), f"Script not found at {SCRIPT_PATH}"

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, (
        f"--help failed. stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    combined = (result.stdout + result.stderr).lower()
    # Must document the env vars it consumes.
    for expected in ("proof_arena_api_url", "admin_api_key", "user_token"):
        assert expected in combined, f"--help output missing reference to {expected}"


# ---------------------------------------------------------------------------
# Orchestration sequence: script calls helpers in the right order and emits
# a structured JSON summary that includes tx signatures + api verification.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifecycle_orchestration_sequence_with_mocks(capsys, monkeypatch):
    """Drive lifecycle.orchestrate() with every step-level helper mocked.

    Asserts:
    - strategies registered before challenge creation
    - challenge created before start
    - start before deterministic finalize
    - finalize before settle
    - settle before read-model verification
    - JSON summary emitted with tx_signatures + api_verification keys
    """
    from src.config import settings

    monkeypatch.setattr(settings, "SOLANA_CLUSTER", "devnet")
    monkeypatch.setattr(settings, "SOLANA_RPC_URL", "https://api.devnet.solana.com")
    monkeypatch.setattr(settings, "PROGRAM_ID", "GFnG5esZ77F4NL3CpSE9tLHG4ExghiQuBB83ZtGYuqcu")
    monkeypatch.setattr(settings, "AUTHORITY_KEYPAIR_PATH", "/tmp/irrelevant.json")

    import scripts.run_devnet_lifecycle as lifecycle

    # Record every step in order.
    sequence: list[str] = []

    async def _fake_register_strategy(http, token, payload):
        sequence.append(f"register_strategy:{payload['agent_name']}")
        agent_id = 100 if "Alpha" in payload["agent_name"] else 101
        return {
            "agent_id": agent_id,
            "submission_hash": "deadbeef" * 8,
            "onchain_tx": f"tx_register_{agent_id}",
        }

    async def _fake_onchain_register_agents(agent_ids, program_client):
        sequence.append(f"onchain_register_agents:{','.join(str(a) for a in agent_ids)}")
        return {
            "register_txs": {str(a): f"tx_onchain_register_{a}" for a in agent_ids},
        }

    async def _fake_create_challenge_via_api(http, admin_key, agent_ids):
        sequence.append("create_challenge")
        return {
            "challenge_id": 500,
            "status": "pending",
            "onchain_txs": {
                "create_challenge": "tx_create_challenge_xyz",
                "create_run": ["tx_create_run_100", "tx_create_run_101"],
            },
        }

    async def _fake_start_challenge_via_api(http, admin_key, challenge_id):
        sequence.append(f"start_challenge:{challenge_id}")
        return {
            "status": "active",
            "onchain_tx": "tx_start_challenge_xyz",
        }

    async def _fake_deterministic_finalize_runs(
        challenge_id, winner_agent_id, winner_ending, loser_agent_id, loser_ending,
        program_client,
    ):
        sequence.append(f"finalize_runs:{challenge_id}")
        return {
            "finalize_txs": {
                str(winner_agent_id): "tx_finalize_winner",
                str(loser_agent_id): "tx_finalize_loser",
            }
        }

    async def _fake_settle_via_service(challenge_id, program_client):
        sequence.append(f"settle:{challenge_id}")
        return {
            "settle_tx": "tx_settle_xyz",
            "winner_agent_id": 100,
            "update_rank_txs": {"100": "tx_rank_100", "101": "tx_rank_101"},
        }

    async def _fake_verify_leaderboard(http):
        sequence.append("verify_leaderboard")
        return True

    async def _fake_verify_challenge_detail(http, challenge_id):
        sequence.append(f"verify_challenge_detail:{challenge_id}")
        return True

    async def _fake_verify_agent_profile(http, agent_id):
        sequence.append(f"verify_agent_profile:{agent_id}")
        return True

    # Mock the HTTP client — the real orchestrator creates one and passes it
    # to the step helpers; step helpers are mocked so the client is unused.
    monkeypatch.setattr(lifecycle, "make_http_client", lambda *_a, **_kw: MagicMock(
        __aenter__=AsyncMock(return_value=MagicMock()),
        __aexit__=AsyncMock(return_value=None),
    ))

    # Mock the program-client factory so no real RPC.
    monkeypatch.setattr(lifecycle, "get_program_client", lambda: MagicMock())

    # Patch every step helper.
    monkeypatch.setattr(lifecycle, "register_strategy", _fake_register_strategy)
    monkeypatch.setattr(lifecycle, "onchain_register_agents", _fake_onchain_register_agents)
    monkeypatch.setattr(lifecycle, "create_challenge_via_api", _fake_create_challenge_via_api)
    monkeypatch.setattr(lifecycle, "start_challenge_via_api", _fake_start_challenge_via_api)
    monkeypatch.setattr(
        lifecycle, "deterministic_finalize_runs", _fake_deterministic_finalize_runs
    )
    monkeypatch.setattr(lifecycle, "settle_via_service", _fake_settle_via_service)
    monkeypatch.setattr(lifecycle, "verify_leaderboard", _fake_verify_leaderboard)
    monkeypatch.setattr(lifecycle, "verify_challenge_detail", _fake_verify_challenge_detail)
    monkeypatch.setattr(lifecycle, "verify_agent_profile", _fake_verify_agent_profile)

    summary = await lifecycle.orchestrate(
        api_url="http://localhost:8000/api/v1",
        admin_api_key="test-admin-key-task16",
        user_tokens=["user-token-1", "user-token-2"],
    )

    # --- Sequence assertions ---
    def _first_with(fragment: str) -> int:
        for idx, s in enumerate(sequence):
            if fragment in s:
                return idx
        raise AssertionError(f"No step containing {fragment!r}. Sequence: {sequence}")

    idx_reg_a = _first_with("register_strategy:Alpha")
    idx_reg_b = _first_with("register_strategy:Beta")
    idx_onchain_reg = _first_with("onchain_register_agents")
    idx_create = _first_with("create_challenge")
    idx_start = _first_with("start_challenge")
    idx_finalize = _first_with("finalize_runs")
    idx_settle = _first_with("settle:")
    idx_lb = _first_with("verify_leaderboard")
    idx_chdetail = _first_with("verify_challenge_detail")
    idx_agent = _first_with("verify_agent_profile")

    assert idx_reg_a < idx_onchain_reg
    assert idx_reg_b < idx_onchain_reg
    assert idx_onchain_reg < idx_create
    assert idx_create < idx_start
    assert idx_start < idx_finalize
    assert idx_finalize < idx_settle
    assert idx_settle < idx_lb
    assert idx_settle < idx_chdetail
    assert idx_settle < idx_agent

    # Agent verification called for BOTH contestants.
    agent_verifications = [s for s in sequence if s.startswith("verify_agent_profile:")]
    assert len(agent_verifications) == 2, f"Expected 2 agent verifications; got {agent_verifications}"

    # --- JSON summary shape ---
    assert isinstance(summary, dict)
    for key in ("tx_signatures", "api_verification"):
        assert key in summary, f"Summary missing key {key}"

    tx_sigs = summary["tx_signatures"]
    for tag in (
        "create_challenge",
        "start_challenge",
        "finalize_run",
        "settle_challenge",
    ):
        assert any(tag in str(k).lower() for k in tx_sigs.keys()) or any(
            tag in str(v).lower() for v in _flatten_values(tx_sigs)
        ), f"tx_signatures missing {tag!r}. Got: {tx_sigs}"

    verification = summary["api_verification"]
    for k in ("leaderboard_ok", "challenge_detail_ok", "agent_profile_ok"):
        assert k in verification
        assert verification[k] is True

    # --- JSON summary on stdout for operator/report capture ---
    out = capsys.readouterr().out
    json_lines = [line for line in out.splitlines() if line.strip().startswith("{")]
    assert json_lines, f"Expected a JSON summary line in stdout; got {out!r}"
    parsed = json.loads(json_lines[-1])
    assert "tx_signatures" in parsed


def _flatten_values(obj):
    """Yield every leaf value in a nested dict/list structure."""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _flatten_values(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _flatten_values(v)
    else:
        yield obj


# ---------------------------------------------------------------------------
# Devnet-only guard.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifecycle_fails_closed_on_non_devnet_cluster(capsys, monkeypatch):
    """Non-devnet cluster → script exits non-zero, never reaches orchestrate()."""
    from src.config import settings

    monkeypatch.setattr(settings, "SOLANA_CLUSTER", "mainnet-beta")
    monkeypatch.setattr(settings, "SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

    import scripts.run_devnet_lifecycle as lifecycle

    # orchestrate() must NOT be called.
    orchestrate_called = False

    async def _should_never_run(*a, **kw):
        nonlocal orchestrate_called
        orchestrate_called = True
        return {}

    monkeypatch.setattr(lifecycle, "orchestrate", _should_never_run)

    exit_code = await lifecycle.main_async(
        api_url="http://localhost:8000/api/v1",
        admin_api_key="test-admin-key-task16",
        user_tokens=["u1", "u2"],
    )
    assert exit_code != 0, "Non-devnet cluster must exit non-zero."
    assert not orchestrate_called, "orchestrate() must not be invoked on mainnet."

    captured = capsys.readouterr()
    combined = (captured.out + captured.err).lower()
    assert "devnet" in combined

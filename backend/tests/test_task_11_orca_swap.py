"""Task 11 — RED tests for OrcaSwapService (Option A, Node subprocess).

Covers (see .taskmaster/docs/task11-edge-case-spec.md):
- B-6 decision artifact presence + Option A commitment
- Devnet-only guard (Layer 2 of the future 3-layer mainnet guard)
- Exact subprocess CLI flag contract
- Base64-stdout → bytes decode
- Invalid-pool stderr pattern → InvalidPoolError
- Generic failure → OrcaSwapError
- Malformed stdout → OrcaSwapError
- Missing Node runtime → OrcaSwapError
- Subprocess timeout → OrcaSwapError + proc kill
- Config surfaces land on settings
- Service + exceptions exported from services package
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-t11")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/unused",
)


# ======================================================================
# B-6 decision artifact
# ======================================================================

_REPO_ROOT = Path(__file__).resolve().parents[3]
_B6_PATH = _REPO_ROOT / ".taskmaster" / "docs" / "task11-b6-decision.md"


def test_b6_decision_artifact_exists():
    assert _B6_PATH.is_file(), f"B-6 decision artifact missing at {_B6_PATH}"


def test_b6_decision_names_option_a():
    text = _B6_PATH.read_text(encoding="utf-8").lower()
    assert "option a" in text
    assert "@orca-so/whirlpools" in text
    assert "§12" in text or "b-6" in text


# ======================================================================
# Helpers — fake asyncio subprocess
# ======================================================================


def _fake_proc(
    *,
    stdout: bytes = b"",
    stderr: bytes = b"",
    returncode: int = 0,
) -> MagicMock:
    """A MagicMock shaped like an ``asyncio.subprocess.Process``."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=returncode)
    return proc


# A realistic-looking unsigned versioned-tx payload (not a real tx — just
# arbitrary bytes that round-trip through base64). Task 11 returns bytes;
# tests assert byte equality, not Solana-tx validity.
_FAKE_TX_BYTES = bytes(range(64))
_FAKE_TX_B64 = base64.b64encode(_FAKE_TX_BYTES).decode("ascii") + "\n"


# ======================================================================
# Guard behavior
# ======================================================================


def test_constructs_with_devnet_cluster():
    from src.services.swap_service import OrcaSwapService

    svc = OrcaSwapService(rpc_url="https://api.devnet.solana.com", cluster="devnet")
    assert svc.cluster == "devnet"


def test_rejects_mainnet_beta_cluster():
    from src.services.swap_service import OrcaSwapService

    with pytest.raises(RuntimeError):
        OrcaSwapService(
            rpc_url="https://api.mainnet-beta.solana.com",
            cluster="mainnet-beta",
        )


def test_rejects_testnet_cluster():
    from src.services.swap_service import OrcaSwapService

    with pytest.raises(RuntimeError):
        OrcaSwapService(rpc_url="https://api.testnet.solana.com", cluster="testnet")


def test_rejects_empty_cluster():
    from src.services.swap_service import OrcaSwapService

    with pytest.raises(RuntimeError):
        OrcaSwapService(rpc_url="https://api.devnet.solana.com", cluster="")


# ======================================================================
# Subprocess contract
# ======================================================================


async def test_subprocess_invoked_with_expected_cli_flags():
    """Contract: prescribed CLI flag pairs + ``--pool`` from service config."""
    from src.services.swap_service import OrcaSwapService

    svc = OrcaSwapService(
        rpc_url="https://api.devnet.solana.com",
        cluster="devnet",
        script_path="scripts/orca_swap.js",
        pool_address="3KBZiL2g8C7tiJ32hTv5v3KM7aK9htpqTw4cTXz1HvPt",
    )
    proc = _fake_proc(stdout=_FAKE_TX_B64.encode("ascii"))

    with patch(
        "src.services.swap_service.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=proc),
    ) as mock_exec:
        await svc.prepare_swap_tx(
            input_mint="So11111111111111111111111111111111111111112",
            output_mint="BRjpCHtyQLNCo8gqRUr8jtdAj5AjPYQaoqbvcZiHok1k",
            amount=1_000_000,
            slippage_bps=50,
            wallet_pubkey="11111111111111111111111111111111",
        )

    assert mock_exec.await_count == 1
    args = mock_exec.await_args.args
    # argv = ("node", "scripts/orca_swap.js", <flag pairs>)
    assert args[0] == "node"
    assert args[1] == "scripts/orca_swap.js"
    flag_pairs = dict(zip(args[2::2], args[3::2]))
    assert flag_pairs == {
        "--input-mint": "So11111111111111111111111111111111111111112",
        "--output-mint": "BRjpCHtyQLNCo8gqRUr8jtdAj5AjPYQaoqbvcZiHok1k",
        "--amount": "1000000",
        "--slippage-bps": "50",
        "--wallet-pubkey": "11111111111111111111111111111111",
        "--rpc-url": "https://api.devnet.solana.com",
        "--pool": "3KBZiL2g8C7tiJ32hTv5v3KM7aK9htpqTw4cTXz1HvPt",
    }


async def test_pool_address_not_configured_raises_invalid_pool_error():
    from src.services.swap_service import InvalidPoolError, OrcaSwapService

    svc = OrcaSwapService(
        rpc_url="https://api.devnet.solana.com",
        cluster="devnet",
        pool_address="",
    )
    with pytest.raises(InvalidPoolError):
        await svc.prepare_swap_tx(
            input_mint="A" * 32,
            output_mint="B" * 32,
            amount=1,
            slippage_bps=50,
            wallet_pubkey="C" * 32,
        )


async def test_prepare_swap_tx_returns_decoded_bytes_from_base64_stdout():
    from src.services.swap_service import OrcaSwapService

    svc = OrcaSwapService(
        rpc_url="https://api.devnet.solana.com",
        cluster="devnet",
        pool_address="3KBZiL2g8C7tiJ32hTv5v3KM7aK9htpqTw4cTXz1HvPt",
    )
    proc = _fake_proc(stdout=_FAKE_TX_B64.encode("ascii"))

    with patch(
        "src.services.swap_service.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=proc),
    ):
        tx_bytes = await svc.prepare_swap_tx(
            input_mint="A" * 32,
            output_mint="B" * 32,
            amount=100,
            slippage_bps=50,
            wallet_pubkey="C" * 32,
        )

    assert isinstance(tx_bytes, bytes)
    assert tx_bytes == _FAKE_TX_BYTES


async def test_invalid_pool_stderr_maps_to_invalid_pool_error():
    from src.services.swap_service import InvalidPoolError, OrcaSwapService

    svc = OrcaSwapService(
        rpc_url="https://api.devnet.solana.com",
        cluster="devnet",
        pool_address="3KBZiL2g8C7tiJ32hTv5v3KM7aK9htpqTw4cTXz1HvPt",
    )
    proc = _fake_proc(
        stdout=b"",
        stderr=b"Whirlpool account not found at 3KBZ...",
        returncode=1,
    )

    with patch(
        "src.services.swap_service.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=proc),
    ):
        with pytest.raises(InvalidPoolError):
            await svc.prepare_swap_tx(
                input_mint="A" * 32,
                output_mint="B" * 32,
                amount=1,
                slippage_bps=50,
                wallet_pubkey="C" * 32,
            )


async def test_generic_failure_maps_to_orca_swap_error():
    from src.services.swap_service import OrcaSwapError, OrcaSwapService

    svc = OrcaSwapService(
        rpc_url="https://api.devnet.solana.com",
        cluster="devnet",
        pool_address="3KBZiL2g8C7tiJ32hTv5v3KM7aK9htpqTw4cTXz1HvPt",
    )
    proc = _fake_proc(
        stdout=b"",
        stderr=b"some other sdk error",
        returncode=2,
    )

    with patch(
        "src.services.swap_service.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=proc),
    ):
        with pytest.raises(OrcaSwapError) as ei:
            await svc.prepare_swap_tx(
                input_mint="A" * 32,
                output_mint="B" * 32,
                amount=1,
                slippage_bps=50,
                wallet_pubkey="C" * 32,
            )
    # Must not accidentally get caught by the InvalidPoolError check.
    from src.services.swap_service import InvalidPoolError

    assert not isinstance(ei.value, InvalidPoolError)
    assert "some other sdk error" in str(ei.value)


async def test_malformed_base64_stdout_raises_orca_swap_error():
    from src.services.swap_service import OrcaSwapError, OrcaSwapService

    svc = OrcaSwapService(
        rpc_url="https://api.devnet.solana.com",
        cluster="devnet",
        pool_address="3KBZiL2g8C7tiJ32hTv5v3KM7aK9htpqTw4cTXz1HvPt",
    )
    # Not valid base64.
    proc = _fake_proc(stdout=b"@@@ not base64 @@@\n")

    with patch(
        "src.services.swap_service.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=proc),
    ):
        with pytest.raises(OrcaSwapError):
            await svc.prepare_swap_tx(
                input_mint="A" * 32,
                output_mint="B" * 32,
                amount=1,
                slippage_bps=50,
                wallet_pubkey="C" * 32,
            )


async def test_node_runtime_missing_raises_orca_swap_error():
    from src.services.swap_service import OrcaSwapError, OrcaSwapService

    svc = OrcaSwapService(
        rpc_url="https://api.devnet.solana.com",
        cluster="devnet",
        pool_address="3KBZiL2g8C7tiJ32hTv5v3KM7aK9htpqTw4cTXz1HvPt",
    )
    with patch(
        "src.services.swap_service.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=FileNotFoundError("node")),
    ):
        with pytest.raises(OrcaSwapError) as ei:
            await svc.prepare_swap_tx(
                input_mint="A" * 32,
                output_mint="B" * 32,
                amount=1,
                slippage_bps=50,
                wallet_pubkey="C" * 32,
            )
    assert "node" in str(ei.value).lower()


async def test_subprocess_timeout_kills_process_and_raises():
    """R2 — if Node hangs past the timeout, kill the process and raise."""
    import asyncio as _asyncio

    from src.services.swap_service import OrcaSwapError, OrcaSwapService

    svc = OrcaSwapService(
        rpc_url="https://api.devnet.solana.com",
        cluster="devnet",
        timeout_secs=0,  # force immediate timeout for test determinism
        pool_address="3KBZiL2g8C7tiJ32hTv5v3KM7aK9htpqTw4cTXz1HvPt",
    )

    proc = _fake_proc()
    # Replace communicate with one that never returns until cancelled.
    async def _hang(*a, **kw):
        await _asyncio.sleep(3600)

    proc.communicate = _hang  # type: ignore[assignment]

    with patch(
        "src.services.swap_service.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=proc),
    ):
        with pytest.raises(OrcaSwapError):
            await svc.prepare_swap_tx(
                input_mint="A" * 32,
                output_mint="B" * 32,
                amount=1,
                slippage_bps=50,
                wallet_pubkey="C" * 32,
            )
    proc.kill.assert_called()


# ======================================================================
# Config + package exports (subtask 11.3)
# ======================================================================


def test_settings_has_v2_hosted_swap_pool_and_usdc_mint_and_script_path():
    from src.config import settings

    # Attribute presence is the contract; values default to ""
    # (ops sets them via .env/docker-compose per PHASE_0_CLOSEOUT_NOTE.md).
    assert hasattr(settings, "V2_HOSTED_SWAP_POOL")
    assert hasattr(settings, "V2_HOSTED_USDC_MINT")
    assert hasattr(settings, "ORCA_SWAP_SCRIPT_PATH")
    assert isinstance(settings.V2_HOSTED_SWAP_POOL, str)
    assert isinstance(settings.V2_HOSTED_USDC_MINT, str)
    assert isinstance(settings.ORCA_SWAP_SCRIPT_PATH, str)


def test_orca_swap_service_exported_from_services_package():
    from src.services import InvalidPoolError, OrcaSwapError, OrcaSwapService

    assert OrcaSwapService is not None
    assert issubclass(InvalidPoolError, OrcaSwapError)


def test_orca_swap_helper_script_file_shipped():
    """The Node helper is part of the deliverable; its presence on disk
    is the unit of work. Actual execution requires ``npm install`` of
    ``@orca-so/whirlpools`` which is an operational step, not Task 11."""
    script = _REPO_ROOT / "agent-rank" / "backend" / "scripts" / "orca_swap.js"
    assert script.is_file(), f"Node helper missing at {script}"


# ======================================================================
# Follow-up: runtime manifest + output_mint enforcement
# ======================================================================


def test_scripts_package_json_declares_required_deps():
    """Without a package.json the Node helper can't be loaded at all
    (ES import syntax requires ``"type": "module"``). Declare the
    runtime deps for @orca-so/whirlpools + @solana/kit."""
    import json as _json

    manifest = (
        _REPO_ROOT / "agent-rank" / "backend" / "scripts" / "package.json"
    )
    assert manifest.is_file(), f"scripts/package.json missing at {manifest}"
    data = _json.loads(manifest.read_text(encoding="utf-8"))

    # ESM scope — orca_swap.js uses `import` syntax.
    assert data.get("type") == "module"

    deps = data.get("dependencies") or {}
    assert "@orca-so/whirlpools" in deps
    assert "@solana/kit" in deps


async def test_mismatched_output_mint_stderr_maps_to_invalid_pool_error():
    """Node helper fetches the Whirlpool and rejects a wrong output_mint
    before tx construction. The stderr includes ``mint`` / ``pool`` so
    the Python classifier routes it to InvalidPoolError, not the generic
    OrcaSwapError bucket."""
    from src.services.swap_service import InvalidPoolError, OrcaSwapService

    svc = OrcaSwapService(
        rpc_url="https://api.devnet.solana.com",
        cluster="devnet",
        pool_address="3KBZiL2g8C7tiJ32hTv5v3KM7aK9htpqTw4cTXz1HvPt",
    )
    proc = _fake_proc(
        stdout=b"",
        stderr=(
            b"input/output mint pair (Aaa -> WRONG) does not match pool "
            b"3KBZiL2g8C7tiJ32hTv5v3KM7aK9htpqTw4cTXz1HvPt sides "
            b"(tokenMintA=So11..., tokenMintB=BRjpCH...)\n"
        ),
        returncode=1,
    )

    with patch(
        "src.services.swap_service.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=proc),
    ):
        with pytest.raises(InvalidPoolError) as ei:
            await svc.prepare_swap_tx(
                input_mint="So11111111111111111111111111111111111111112",
                output_mint="WRONGWRONGWRONGWRONGWRONGWRONGWR",
                amount=1_000_000,
                slippage_bps=50,
                wallet_pubkey="11111111111111111111111111111111",
            )
    assert "mint" in str(ei.value).lower() or "pool" in str(ei.value).lower()


def test_helper_script_parses_as_esm_module():
    """Cheap structural check that the shipped helper is actually a
    loadable ES module (catches silent regressions like losing the
    ``"type": "module"`` package.json scope)."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node not available in this environment")

    script = _REPO_ROOT / "agent-rank" / "backend" / "scripts" / "orca_swap.js"
    res = subprocess.run(
        [node, "--check", str(script)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, (
        f"node --check failed on orca_swap.js:\n"
        f"stdout={res.stdout}\nstderr={res.stderr}"
    )

"""Task 9 — RED tests for WalletService.create_hosted_wallet.

Covers (see .taskmaster/docs/task9-edge-case-spec.md):
- Devnet-only hosted-wallet guard (Layer 1 of the future 3-layer mainnet guard)
- PrivySigningService dependency wiring
- Exact request body shape (``policy_ids`` array, not ``policy_id`` scalar)
- Exact signed URL (full URL, not path-only; matches Phase 0 byte-equal)
- Header composition (only ``privy-authorization-signature``; no timestamp header)
- 200 success parsing + error-response paths
- Regression: existing ``create_benchmark_wallet`` still works with ``signing_service=None``
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest


os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-t9")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/unused",
)


PRIVY_API_BASE_EXPECTED = "https://api.privy.io/v1"


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _mock_httpx_response(
    status: int = 200, json_body: dict | None = None, text: str = ""
):
    """Return a MagicMock that quacks like an httpx.Response."""
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=json_body or {})
    resp.text = text or (str(json_body) if json_body else "")
    return resp


def _make_service(
    cluster: str = "devnet",
    *,
    signing_service=None,
    client=None,
):
    """Construct a WalletService without touching treasury/keypair load paths.

    We bypass __init__'s full setup by building a bare instance with only the
    attributes ``create_hosted_wallet`` touches: ``cluster``, ``rpc_url``,
    ``client``, ``signing_service``.
    """
    from src.services.wallet_service import WalletService

    svc = WalletService.__new__(WalletService)
    # Minimal state for create_hosted_wallet path
    svc.cluster = cluster
    svc.rpc_url = f"https://api.{cluster}.solana.com"
    svc.signing_service = signing_service
    svc.client = client if client is not None else MagicMock()
    # Defaults that create_benchmark_wallet would otherwise rely on —
    # leave unset; hosted-wallet tests don't exercise that path.
    return svc


def _signing_service_mock(return_sig: str = "sig-base64-x"):
    mock = MagicMock()
    mock.sign_request = MagicMock(return_value=return_sig)
    return mock


# ======================================================================
# Guard behavior
# ======================================================================


async def test_non_devnet_cluster_rejected_mainnet_beta():
    from src.services.wallet_service import ChainMismatchError

    svc = _make_service(
        cluster="mainnet-beta", signing_service=_signing_service_mock()
    )
    with pytest.raises(ChainMismatchError):
        await svc.create_hosted_wallet(
            policy_id="pol-x", authorization_pubkey="pub-b64"
        )
    # No HTTP call made
    assert not svc.client.post.called


async def test_non_devnet_cluster_rejected_testnet():
    from src.services.wallet_service import ChainMismatchError

    svc = _make_service(cluster="testnet", signing_service=_signing_service_mock())
    with pytest.raises(ChainMismatchError):
        await svc.create_hosted_wallet(
            policy_id="pol-x", authorization_pubkey="pub-b64"
        )


async def test_devnet_cluster_allowed_through_guard():
    svc = _make_service(
        cluster="devnet",
        signing_service=_signing_service_mock(),
        client=AsyncMock(
            post=AsyncMock(
                return_value=_mock_httpx_response(
                    200, {"id": "w-id", "address": "sol-addr"}
                )
            )
        ),
    )
    out = await svc.create_hosted_wallet(
        policy_id="pol-x", authorization_pubkey="pub-b64"
    )
    assert out == {"id": "w-id", "address": "sol-addr"}


# ======================================================================
# Dependency wiring
# ======================================================================


async def test_missing_signing_service_fails_clearly():
    """No signing service injected → ValueError at create_hosted_wallet call."""
    svc = _make_service(cluster="devnet", signing_service=None)
    with pytest.raises(ValueError):
        await svc.create_hosted_wallet(
            policy_id="pol-x", authorization_pubkey="pub-b64"
        )


async def test_sign_request_called_exactly_once_with_expected_shape():
    signing = _signing_service_mock()
    svc = _make_service(
        cluster="devnet",
        signing_service=signing,
        client=AsyncMock(
            post=AsyncMock(
                return_value=_mock_httpx_response(
                    200, {"id": "w", "address": "a"}
                )
            )
        ),
    )
    await svc.create_hosted_wallet(
        policy_id="pol-42", authorization_pubkey="pub-b64"
    )
    assert signing.sign_request.call_count == 1
    args, kwargs = signing.sign_request.call_args
    # Accept positional or kwarg form.
    method = kwargs.get("method", args[0] if args else None)
    url = kwargs.get("url", args[1] if len(args) > 1 else None)
    body = kwargs.get("body", args[2] if len(args) > 2 else None)
    assert method == "POST"
    assert url == f"{PRIVY_API_BASE_EXPECTED}/wallets"
    assert body is not None


# ======================================================================
# Request construction
# ======================================================================


async def test_request_body_uses_policy_ids_array_not_singular():
    client = AsyncMock(
        post=AsyncMock(
            return_value=_mock_httpx_response(
                200, {"id": "w", "address": "a"}
            )
        )
    )
    svc = _make_service(
        cluster="devnet",
        signing_service=_signing_service_mock(),
        client=client,
    )
    await svc.create_hosted_wallet(
        policy_id="pol-42", authorization_pubkey="pub-b64"
    )
    _, kwargs = client.post.call_args
    body = kwargs["json"]
    assert body["chain_type"] == "solana"
    assert body["owner"] == {"public_key": "pub-b64"}
    assert body["policy_ids"] == ["pol-42"]  # array, plural
    assert "policy_id" not in body  # no stale singular key


async def test_only_authorization_signature_header_added():
    """privy-authorization-signature ONLY. No privy-authorization-timestamp header."""
    client = AsyncMock(
        post=AsyncMock(
            return_value=_mock_httpx_response(
                200, {"id": "w", "address": "a"}
            )
        )
    )
    svc = _make_service(
        cluster="devnet",
        signing_service=_signing_service_mock(return_sig="sig-abc"),
        client=client,
    )
    await svc.create_hosted_wallet(
        policy_id="pol-x", authorization_pubkey="pub-b64"
    )
    _, kwargs = client.post.call_args
    headers = kwargs.get("headers") or {}
    assert headers.get("privy-authorization-signature") == "sig-abc"
    # Stale Task 9 text mentioned this header; it is NOT part of the Phase 0
    # posture. Must not be present.
    assert "privy-authorization-timestamp" not in headers


async def test_signed_url_is_full_url_not_path_only():
    """The URL passed to sign_request is the full Privy URL, byte-equal to Phase 0."""
    signing = _signing_service_mock()
    svc = _make_service(
        cluster="devnet",
        signing_service=signing,
        client=AsyncMock(
            post=AsyncMock(
                return_value=_mock_httpx_response(
                    200, {"id": "w", "address": "a"}
                )
            )
        ),
    )
    await svc.create_hosted_wallet(
        policy_id="pol-x", authorization_pubkey="pub-b64"
    )
    _, kwargs = signing.sign_request.call_args
    url = kwargs.get("url") or signing.sign_request.call_args.args[1]
    assert url == "https://api.privy.io/v1/wallets"
    # Guard against reverting to path-only
    assert url != "/wallets"


# ======================================================================
# Response handling
# ======================================================================


async def test_200_with_id_and_address_returns_dict():
    svc = _make_service(
        cluster="devnet",
        signing_service=_signing_service_mock(),
        client=AsyncMock(
            post=AsyncMock(
                return_value=_mock_httpx_response(
                    200, {"id": "wid-1", "address": "AbC..."}
                )
            )
        ),
    )
    out = await svc.create_hosted_wallet(
        policy_id="pol-x", authorization_pubkey="pub-b64"
    )
    assert out == {"id": "wid-1", "address": "AbC..."}


async def test_non_200_raises_privy_api_error_with_operation_name():
    from src.services.wallet_service import PrivyAPIError

    svc = _make_service(
        cluster="devnet",
        signing_service=_signing_service_mock(),
        client=AsyncMock(
            post=AsyncMock(
                return_value=_mock_httpx_response(
                    400, {"code": "policy_violation"}, text='{"code":"policy_violation"}'
                )
            )
        ),
    )
    with pytest.raises(PrivyAPIError) as ei:
        await svc.create_hosted_wallet(
            policy_id="pol-x", authorization_pubkey="pub-b64"
        )
    assert ei.value.status_code == 400
    assert ei.value.operation == "create_hosted_wallet"
    # Structured error body preserved in detail
    assert "policy_violation" in ei.value.detail


async def test_200_with_missing_id_raises():
    from src.services.wallet_service import PrivyAPIError

    svc = _make_service(
        cluster="devnet",
        signing_service=_signing_service_mock(),
        client=AsyncMock(
            post=AsyncMock(
                return_value=_mock_httpx_response(
                    200, {"address": "AbC..."}
                )
            )
        ),
    )
    with pytest.raises(PrivyAPIError):
        await svc.create_hosted_wallet(
            policy_id="pol-x", authorization_pubkey="pub-b64"
        )


async def test_200_with_missing_address_raises():
    from src.services.wallet_service import PrivyAPIError

    svc = _make_service(
        cluster="devnet",
        signing_service=_signing_service_mock(),
        client=AsyncMock(
            post=AsyncMock(
                return_value=_mock_httpx_response(200, {"id": "w"})
            )
        ),
    )
    with pytest.raises(PrivyAPIError):
        await svc.create_hosted_wallet(
            policy_id="pol-x", authorization_pubkey="pub-b64"
        )


# ======================================================================
# Regression safety
# ======================================================================


def test_walletservice_init_still_accepts_no_signing_service():
    """Existing V1 callers that don't pass signing_service must still construct cleanly."""
    import inspect

    from src.services.wallet_service import WalletService

    sig = inspect.signature(WalletService.__init__)
    # signing_service parameter exists
    assert "signing_service" in sig.parameters
    # And it has a default (so existing callers are unaffected)
    assert sig.parameters["signing_service"].default is None

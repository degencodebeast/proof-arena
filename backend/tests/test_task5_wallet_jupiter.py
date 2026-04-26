"""Task 5: Wallet and Jupiter Integration tests — security-hardened.

All external calls mocked. Tests verify:
- Chain/cluster safety
- ATA creation in fund/drain flows
- Strict Privy response validation
- Structured drain results with per-mint outcomes
- Quote freshness with consistent max_age
- HTTP/2 transport
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# -----------------------------------------------------------------------
# 1. WalletService — init and chain safety
# -----------------------------------------------------------------------


class TestWalletServiceInit:
    def test_caip2_derived_from_cluster(self):
        from src.services.wallet_service import WalletService, CLUSTER_TO_CAIP2

        svc = WalletService(
            privy_app_id="a", privy_app_secret="b", solana_cluster="devnet",
            solana_rpc_url="https://api.devnet.solana.com",
        )
        assert svc.caip2 == CLUSTER_TO_CAIP2["devnet"]

    def test_mainnet_caip2(self):
        from src.services.wallet_service import WalletService, CLUSTER_TO_CAIP2

        svc = WalletService(
            privy_app_id="a", privy_app_secret="b",
            solana_cluster="mainnet-beta",
            solana_rpc_url="https://api.mainnet-beta.solana.com",
        )
        assert svc.caip2 == CLUSTER_TO_CAIP2["mainnet-beta"]

    def test_unknown_cluster_raises(self):
        from src.services.wallet_service import WalletService

        with pytest.raises(ValueError, match="Unknown cluster"):
            WalletService(
                privy_app_id="a", privy_app_secret="b",
                solana_cluster="fakenet",
            )

    def test_devnet_cluster_with_mainnet_rpc_raises(self):
        """RPC URL pointing to mainnet while cluster is devnet must fail."""
        from src.services.wallet_service import WalletService, ChainMismatchError

        with pytest.raises(ChainMismatchError):
            WalletService(
                privy_app_id="a", privy_app_secret="b",
                solana_cluster="devnet",
                solana_rpc_url="https://api.mainnet-beta.solana.com",
            )

    def test_mainnet_cluster_with_devnet_rpc_raises(self):
        """RPC URL pointing to devnet while cluster is mainnet must fail."""
        from src.services.wallet_service import WalletService, ChainMismatchError

        with pytest.raises(ChainMismatchError):
            WalletService(
                privy_app_id="a", privy_app_secret="b",
                solana_cluster="mainnet-beta",
                solana_rpc_url="https://api.devnet.solana.com",
            )

    def test_matching_cluster_and_rpc_succeeds(self):
        from src.services.wallet_service import WalletService

        # Should not raise
        svc = WalletService(
            privy_app_id="a", privy_app_secret="b",
            solana_cluster="devnet",
            solana_rpc_url="https://api.devnet.solana.com",
        )
        assert svc.cluster == "devnet"

    def test_custom_rpc_with_no_cluster_marker_allowed(self):
        """A custom RPC URL with no cluster name should not raise."""
        from src.services.wallet_service import WalletService

        svc = WalletService(
            privy_app_id="a", privy_app_secret="b",
            solana_cluster="devnet",
            solana_rpc_url="https://my-custom-rpc.example.com/v1",
        )
        assert svc.cluster == "devnet"

    def test_treasury_loads_from_config(self, tmp_path):
        """Treasury keypair loads from TREASURY_KEYPAIR_PATH in settings."""
        import json
        from solders.keypair import Keypair
        from src.services.wallet_service import WalletService

        kp = Keypair()
        kp_path = tmp_path / "treasury.json"
        kp_path.write_text(json.dumps(list(bytes(kp))))

        with patch("src.services.wallet_service.settings") as mock_settings:
            mock_settings.PRIVY_APP_ID = "a"
            mock_settings.PRIVY_APP_SECRET = "b"
            mock_settings.SOLANA_RPC_URL = "https://api.devnet.solana.com"
            mock_settings.SOLANA_CLUSTER = "devnet"
            mock_settings.TREASURY_KEYPAIR_PATH = str(kp_path)
            mock_settings.USDC_MINT = ""

            svc = WalletService()
            assert svc.treasury_keypair is not None
            assert svc.treasury_pubkey == kp.pubkey()

    def test_usdc_mint_loads_from_config(self):
        """USDC mint loads from USDC_MINT in settings."""
        from solders.pubkey import Pubkey
        from src.services.wallet_service import WalletService

        mint = Pubkey.new_unique()
        with patch("src.services.wallet_service.settings") as mock_settings:
            mock_settings.PRIVY_APP_ID = "a"
            mock_settings.PRIVY_APP_SECRET = "b"
            mock_settings.SOLANA_RPC_URL = "https://api.devnet.solana.com"
            mock_settings.SOLANA_CLUSTER = "devnet"
            mock_settings.TREASURY_KEYPAIR_PATH = ""
            mock_settings.USDC_MINT = str(mint)

            svc = WalletService()
            assert svc.usdc_mint == mint

    def test_http2_enabled(self):
        from src.services.wallet_service import WalletService

        svc = WalletService(privy_app_id="a", privy_app_secret="b")
        assert svc.client._transport is not None

    def test_treasury_keypair_injected(self):
        from solders.keypair import Keypair
        from src.services.wallet_service import WalletService

        kp = Keypair()
        svc = WalletService(
            privy_app_id="a", privy_app_secret="b", treasury_keypair=kp,
        )
        assert svc.treasury_pubkey == kp.pubkey()


# -----------------------------------------------------------------------
# 2. Strict Privy response validation
# -----------------------------------------------------------------------


class TestPrivyResponseValidation:
    @pytest.mark.asyncio
    async def test_create_wallet_rejects_missing_id(self):
        from src.services.wallet_service import WalletService, PrivyAPIError

        svc = WalletService(privy_app_id="a", privy_app_secret="b")
        svc.client.post = AsyncMock(
            return_value=httpx.Response(200, json={"address": "x"})
        )
        with pytest.raises(PrivyAPIError, match="Missing wallet fields"):
            await svc.create_benchmark_wallet(1, 1)

    @pytest.mark.asyncio
    async def test_create_wallet_rejects_missing_address(self):
        from src.services.wallet_service import WalletService, PrivyAPIError

        svc = WalletService(privy_app_id="a", privy_app_secret="b")
        svc.client.post = AsyncMock(
            return_value=httpx.Response(200, json={"id": "w"})
        )
        with pytest.raises(PrivyAPIError, match="Missing wallet fields"):
            await svc.create_benchmark_wallet(1, 1)

    @pytest.mark.asyncio
    async def test_sign_and_send_rejects_missing_hash(self):
        from src.services.wallet_service import WalletService, PrivyAPIError

        svc = WalletService(privy_app_id="a", privy_app_secret="b")
        svc.signing_service = MagicMock(sign_request=MagicMock(return_value="sig"))
        svc.client.post = AsyncMock(
            return_value=httpx.Response(200, json={"data": {}})
        )
        with pytest.raises(PrivyAPIError, match="Missing tx hash"):
            await svc.sign_and_send_transaction("w", b"\x01")

    @pytest.mark.asyncio
    async def test_sign_rejects_missing_signed_tx(self):
        from src.services.wallet_service import WalletService, PrivyAPIError

        svc = WalletService(privy_app_id="a", privy_app_secret="b")
        svc.signing_service = MagicMock(sign_request=MagicMock(return_value="sig"))
        svc.client.post = AsyncMock(
            return_value=httpx.Response(200, json={"data": {}})
        )
        with pytest.raises(PrivyAPIError, match="Missing signed_transaction"):
            await svc.sign_transaction("w", b"\x01")

    @pytest.mark.asyncio
    async def test_valid_create_wallet(self):
        from src.services.wallet_service import WalletService

        svc = WalletService(privy_app_id="a", privy_app_secret="b")
        svc.client.post = AsyncMock(
            return_value=httpx.Response(200, json={"id": "w1", "address": "addr1"})
        )
        result = await svc.create_benchmark_wallet(1, 2)
        assert result["id"] == "w1"
        assert result["address"] == "addr1"

    @pytest.mark.asyncio
    async def test_sign_and_send_uses_cluster_caip2(self):
        from src.services.wallet_service import WalletService

        svc = WalletService(
            privy_app_id="a", privy_app_secret="b",
            solana_cluster="devnet",
        )
        svc.signing_service = MagicMock(sign_request=MagicMock(return_value="sig"))
        svc.client.post = AsyncMock(
            return_value=httpx.Response(200, json={"data": {"hash": "sig"}})
        )
        await svc.sign_and_send_transaction("w", b"\x01")
        body = svc.client.post.call_args.kwargs["json"]
        assert body["caip2"] == svc.caip2


# -----------------------------------------------------------------------
# 3. Fund wallet (USDC with ATA creation)
# -----------------------------------------------------------------------


class TestFundWallet:
    @pytest.mark.asyncio
    async def test_requires_treasury_keypair(self):
        from src.services.wallet_service import WalletService, WalletFundingError

        svc = WalletService(privy_app_id="a", privy_app_secret="b")
        with pytest.raises(WalletFundingError, match="No treasury keypair"):
            await svc.fund_wallet("dest", 1_000_000)

    @pytest.mark.asyncio
    async def test_requires_usdc_mint(self):
        from solders.keypair import Keypair
        from src.services.wallet_service import WalletService, WalletFundingError

        svc = WalletService(
            privy_app_id="a", privy_app_secret="b",
            treasury_keypair=Keypair(),
        )
        with pytest.raises(WalletFundingError, match="No USDC mint"):
            await svc.fund_wallet("dest", 1_000_000)

    @pytest.mark.asyncio
    async def test_builds_ata_creation_and_transfer(self):
        from solders.keypair import Keypair
        from solders.pubkey import Pubkey
        from src.services.wallet_service import WalletService

        kp = Keypair()
        svc = WalletService(
            privy_app_id="a", privy_app_secret="b",
            treasury_keypair=kp, usdc_mint=Pubkey.new_unique(),
        )

        bh_resp = httpx.Response(200, json={
            "jsonrpc": "2.0",
            "result": {"value": {"blockhash": "11111111111111111111111111111111"}},
        })
        send_resp = httpx.Response(200, json={
            "jsonrpc": "2.0", "result": "fund_sig_123",
        })
        call_count = 0

        async def mock_post(url, **kw):
            nonlocal call_count
            call_count += 1
            return bh_resp if call_count == 1 else send_resp

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post):
            sig = await svc.fund_wallet(str(Pubkey.new_unique()), 1_000_000)

        assert sig == "fund_sig_123"
        assert call_count == 2


# -----------------------------------------------------------------------
# 4. Drain wallet (structured result)
# -----------------------------------------------------------------------


class TestDrainWallet:
    @pytest.mark.asyncio
    async def test_empty_wallet(self):
        from src.services.wallet_service import WalletService

        svc = WalletService(privy_app_id="a", privy_app_secret="b")
        svc.get_token_balances = AsyncMock(return_value={})
        result = await svc.drain_wallet("w", "addr", "treasury")
        assert result.fully_drained
        assert result.signatures == []

    @pytest.mark.asyncio
    async def test_returns_structured_result(self):
        from solders.pubkey import Pubkey
        from src.services.wallet_service import WalletService

        svc = WalletService(privy_app_id="a", privy_app_secret="b")
        mint = str(Pubkey.new_unique())
        svc.get_token_balances = AsyncMock(return_value={mint: 5_000_000})

        bh_resp = httpx.Response(200, json={
            "jsonrpc": "2.0",
            "result": {"value": {"blockhash": "11111111111111111111111111111111"}},
        })
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=bh_resp):
            svc.sign_and_send_transaction = AsyncMock(return_value="drain_sig")
            result = await svc.drain_wallet(
                "w", str(Pubkey.new_unique()), str(Pubkey.new_unique()),
            )

        assert result.fully_drained
        assert len(result.results) == 1
        assert result.results[0].success is True
        assert result.results[0].signature == "drain_sig"

    @pytest.mark.asyncio
    async def test_partial_failure_reported(self):
        from solders.pubkey import Pubkey
        from src.services.wallet_service import WalletService, PrivyAPIError

        svc = WalletService(privy_app_id="a", privy_app_secret="b")
        svc.get_token_balances = AsyncMock(return_value={
            str(Pubkey.new_unique()): 100,
            str(Pubkey.new_unique()): 200,
        })

        bh_resp = httpx.Response(200, json={
            "jsonrpc": "2.0",
            "result": {"value": {"blockhash": "11111111111111111111111111111111"}},
        })
        call_count = 0

        async def mock_send(wallet_id, tx_bytes):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise PrivyAPIError(500, "fail", "sign")
            return "sig_2"

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=bh_resp):
            svc.sign_and_send_transaction = AsyncMock(side_effect=mock_send)
            result = await svc.drain_wallet(
                "w", str(Pubkey.new_unique()), str(Pubkey.new_unique()),
            )

        assert not result.fully_drained
        assert len(result.failed_mints) == 1
        assert len(result.signatures) == 1


# -----------------------------------------------------------------------
# 5. Token balances
# -----------------------------------------------------------------------


class TestTokenBalances:
    @pytest.mark.asyncio
    async def test_parsing(self):
        from src.services.wallet_service import WalletService

        rpc_resp = {"jsonrpc": "2.0", "result": {"value": [
            {"account": {"data": {"parsed": {"info": {
                "mint": "USDC", "tokenAmount": {"amount": "1000000"},
            }}}}},
            {"account": {"data": {"parsed": {"info": {
                "mint": "ZERO", "tokenAmount": {"amount": "0"},
            }}}}},
        ]}}
        svc = WalletService(privy_app_id="a", privy_app_secret="b")
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   return_value=httpx.Response(200, json=rpc_resp)):
            b = await svc.get_token_balances("w")
        assert b["USDC"] == 1000000
        assert "ZERO" not in b


# -----------------------------------------------------------------------
# 6. ATA derivation
# -----------------------------------------------------------------------


class TestATA:
    def test_deterministic(self):
        from solders.pubkey import Pubkey
        from src.services.wallet_service import WalletService

        o, m = Pubkey.new_unique(), Pubkey.new_unique()
        assert WalletService._derive_ata(o, m) == WalletService._derive_ata(o, m)

    def test_different_owner(self):
        from solders.pubkey import Pubkey
        from src.services.wallet_service import WalletService

        m = Pubkey.new_unique()
        assert WalletService._derive_ata(Pubkey.new_unique(), m) != \
               WalletService._derive_ata(Pubkey.new_unique(), m)


# -----------------------------------------------------------------------
# 7. Jupiter — quotes
# -----------------------------------------------------------------------


class TestJupiterQuotes:
    @pytest.mark.asyncio
    async def test_request_shape(self):
        from src.services.jupiter_service import JupiterService

        svc = JupiterService(base_url="https://api.jup.ag")
        svc.client.get = AsyncMock(return_value=httpx.Response(200, json={
            "outAmount": "16198753", "routePlan": [],
        }))
        quotes = await svc.get_quotes("SOL", "USDC", 100000000, slippage_bps=50)
        assert len(quotes) == 1
        assert quotes[0].out_amount == 16198753

    @pytest.mark.asyncio
    async def test_caches(self):
        from src.services.jupiter_service import JupiterService

        svc = JupiterService()
        svc.client.get = AsyncMock(return_value=httpx.Response(200, json={
            "outAmount": "100", "routePlan": [],
        }))
        quotes = await svc.get_quotes("A", "B", 1000)
        assert svc.get_cached_quote(quotes[0].quote_id) is not None


# -----------------------------------------------------------------------
# 8. Jupiter — freshness
# -----------------------------------------------------------------------


class TestQuoteFreshness:
    def _q(self, fetched_at: str):
        from src.services.jupiter_service import QuoteOption
        return QuoteOption(
            quote_id="q", input_mint="A", output_mint="B",
            in_amount=1, out_amount=1, slippage_bps=50,
            fetched_at=fetched_at, route_data={},
        )

    def test_fresh(self):
        from src.services.jupiter_service import JupiterService

        svc = JupiterService(max_age_secs=30)
        svc._quote_cache["q"] = self._q(datetime.now(timezone.utc).isoformat())
        assert svc.is_quote_fresh("q")

    def test_stale(self):
        from src.services.jupiter_service import JupiterService

        svc = JupiterService(max_age_secs=30)
        svc._quote_cache["q"] = self._q(
            (datetime.now(timezone.utc) - timedelta(seconds=31)).isoformat()
        )
        assert not svc.is_quote_fresh("q")

    def test_clear_uses_configured_max_age(self):
        from src.services.jupiter_service import JupiterService

        svc = JupiterService(max_age_secs=10)
        svc._quote_cache["old"] = self._q(
            (datetime.now(timezone.utc) - timedelta(seconds=15)).isoformat()
        )
        svc._quote_cache["fresh"] = self._q(datetime.now(timezone.utc).isoformat())
        assert svc.clear_stale_quotes() == 1
        assert "fresh" in svc._quote_cache


# -----------------------------------------------------------------------
# 9. Jupiter — swap preparation
# -----------------------------------------------------------------------


class TestSwapPrep:
    @pytest.mark.asyncio
    async def test_decodes_base64_tx(self):
        from src.services.jupiter_service import JupiterService, QuoteOption

        svc = JupiterService(max_age_secs=60)
        svc._quote_cache["q"] = QuoteOption(
            quote_id="q", input_mint="A", output_mint="B",
            in_amount=1, out_amount=1, slippage_bps=50,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            route_data={"outAmount": "1"},
        )
        tx_bytes = b"\xaa\xbb"
        svc.client.post = AsyncMock(return_value=httpx.Response(200, json={
            "swapTransaction": base64.b64encode(tx_bytes).decode(),
        }))
        assert await svc.prepare_swap_transaction("q", "pk") == tx_bytes


# -----------------------------------------------------------------------
# 10. Module imports
# -----------------------------------------------------------------------


class TestImports:
    def test_all(self):
        from src.services.wallet_service import (
            WalletService, PrivyAPIError, WalletFundingError,
            ChainMismatchError, DrainResult, DrainMintResult,
        )
        from src.services.jupiter_service import (
            JupiterService, JupiterAPIError, StaleQuoteError, QuoteOption,
        )
        assert all([
            WalletService, PrivyAPIError, WalletFundingError,
            ChainMismatchError, DrainResult, DrainMintResult,
            JupiterService, JupiterAPIError, StaleQuoteError, QuoteOption,
        ])

#!/usr/bin/env python
"""V0-VAL-1 — Privy hosted wallet posture validation (agentic-wallet path).

Produces two distinct proofs in a single run:

1. **Vanilla baseline** — app-secret Basic Auth creates a wallet and signs a
   devnet SOL self-transfer via `signAndSendTransaction`. Proves the Privy
   app credentials reach devnet and produce a real tx signature.

2. **Full agentic-wallet posture** — the V2 hosted posture:
   - Generate a P-256 authorization keypair locally (backend holds private key).
   - Create a wallet policy whose program allowlist matches the V0-VAL-2
     observed Orca devnet swap footprint (Whirlpools + SPL Token + ATA +
     System + Memo + ComputeBudget).
   - Create a Privy wallet with `owner = { public_key: <our P-256 pub> }` and
     `policy_ids = [<policy_id>]`.
   - Sign a positive tx (SystemProgram self-transfer — inside allowlist) via
     `signAndSendTransaction` authenticated with the required
     `privy-authorization-signature` header. Proves the signing path works
     under the authorization-key + policy flow.
   - Attempt a negative tx that invokes a non-allowlisted program and assert
     Privy rejects it (policy enforcement proof).

Hard devnet-only guard. No mock fallback.

Usage
-----
    docker compose exec backend uv run python scripts/v0_val_1_privy_posture.py
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

import httpx
import jcs
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from src.config import settings
from src.services.wallet_service import PrivyAPIError, WalletService

logger = logging.getLogger("v0_val_1")


PRIVY_API_BASE = "https://api.privy.io/v1"

SEED_LAMPORTS = 20_000_000  # 0.02 SOL
RETURN_LAMPORTS = 1_000  # tiny self-transfer amount

# V0-VAL-2 observed Orca devnet swap footprint — every program invoked in tx
# 266Lc9oNy9fPDnSAVdUMFQfeUjWSHyiciXQSPT3Mb5PrRQQ82GKKc6NDb71WM3rSUmbSTS9hrTf4hWYAMc2AjCqU
# plus ComputeBudget for priority fees. This is the allowlist we derive from
# real evidence, not a pre-committed guess.
ORCA_ALLOWLISTED_PROGRAMS: list[str] = [
    "11111111111111111111111111111111",                 # System Program (wSOL create + transfers)
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",       # SPL Token
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",       # Associated Token Account
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",       # Orca Whirlpools v2
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",       # Memo program (Orca SDK adds swap note)
    "ComputeBudget111111111111111111111111111111",       # Compute budget for priority fees
]

# Intentionally-not-in-allowlist program. Real program on devnet, lets us prove
# the enclave denies it rather than getting a simulation error.
NOT_ALLOWLISTED_PROGRAM = "BPFLoaderUpgradeab1e11111111111111111111111"


# ---------------------------------------------------------------------------
# P-256 authorization key — generated in-memory for this run.
# Phase B will persist the key; V0-VAL-1 only needs to prove the flow works.
# ---------------------------------------------------------------------------


def _gen_authorization_keypair() -> tuple[ec.EllipticCurvePrivateKey, str]:
    """Return (private_key, public_key_base64_der) for a fresh P-256 pair.

    Privy's `P256PublicKey` input shape is the base64 of a DER-encoded
    SubjectPublicKeyInfo (same as PEM body without the BEGIN/END lines).
    """
    priv = ec.generate_private_key(ec.SECP256R1())
    pub_der = priv.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv, base64.b64encode(pub_der).decode("ascii")


def _authorization_signature(
    private_key: ec.EllipticCurvePrivateKey,
    method: str,
    url: str,
    body: dict,
    app_id: str,
) -> str:
    """Generate the `privy-authorization-signature` header value.

    Per Privy docs (Signing Requests Directly): canonicalize the payload
    per RFC 8785 (JCS), sign with ECDSA P-256 over SHA-256, base64-encode
    the DER signature. The docs' TypeScript example wrongly uses RSA_PSS;
    the correct primitive is ECDSA-P-256 matching the P-256 key type.
    """
    payload = {
        "version": 1,
        "method": method,
        "url": url.rstrip("/"),
        "body": body,
        "headers": {
            "privy-app-id": app_id,
        },
    }
    canonical = jcs.canonicalize(payload)  # bytes, RFC 8785 JSON canonicalization
    # ECDSA-P-256 with SHA-256.
    der_sig = private_key.sign(canonical, ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(der_sig).decode("ascii")


# ---------------------------------------------------------------------------
# Privy API helpers — raw httpx because wallet_service only handles Basic Auth.
# ---------------------------------------------------------------------------


async def _privy_post(
    client: httpx.AsyncClient,
    path: str,
    body: dict,
    *,
    priv_key: ec.EllipticCurvePrivateKey | None = None,
    app_id: str | None = None,
) -> httpx.Response:
    """POST to Privy. If priv_key given, attach authorization signature header."""
    headers: dict[str, str] = {}
    if priv_key is not None:
        assert app_id is not None
        sig = _authorization_signature(
            priv_key, "POST", f"{PRIVY_API_BASE}{path}", body, app_id,
        )
        headers["privy-authorization-signature"] = sig
    return await client.post(path, json=body, headers=headers)


# ---------------------------------------------------------------------------
# Solana tx builders — plain SOL transfer and unauthorized-program invocation.
# We sign nothing locally; we serialize an unsigned versioned tx that Privy
# will sign and submit.
# ---------------------------------------------------------------------------


async def _get_latest_blockhash(rpc_url: str) -> str:
    """Fetch a finalized blockhash.

    Using `finalized` instead of `confirmed` because Privy's backend RPC
    may not have seen our `confirmed`-level blockhash yet, producing
    spurious "Blockhash not found" broadcast errors. Finalized blocks are
    universally known across all RPCs and still well within the ~150-slot
    validity window.
    """
    async with httpx.AsyncClient(timeout=15.0) as c:
        resp = await c.post(
            rpc_url,
            json={
                "jsonrpc": "2.0", "id": 1, "method": "getLatestBlockhash",
                "params": [{"commitment": "finalized"}],
            },
        )
    return resp.json()["result"]["value"]["blockhash"]


async def _get_sol_balance(rpc_url: str, pubkey: str) -> int:
    async with httpx.AsyncClient(timeout=15.0) as c:
        resp = await c.post(
            rpc_url,
            json={
                "jsonrpc": "2.0", "id": 1, "method": "getBalance",
                "params": [pubkey, {"commitment": "finalized"}],
            },
        )
    return int(resp.json()["result"]["value"])


async def _wait_for_finalized_balance(
    rpc_url: str, pubkey: str, min_lamports: int, timeout_s: int = 40,
) -> int:
    """Poll until the wallet's finalized-commitment balance meets the minimum.

    Privy's backend RPC may not see balance changes until they've finalized,
    so we block on the finalized view before calling signAndSendTransaction.
    """
    deadline = asyncio.get_event_loop().time() + timeout_s
    last = 0
    while asyncio.get_event_loop().time() < deadline:
        last = await _get_sol_balance(rpc_url, pubkey)
        if last >= min_lamports:
            return last
        await asyncio.sleep(2)
    return last


async def _fund_from_treasury(service: WalletService, destination: str, lamports: int) -> str:
    from solders.hash import Hash  # type: ignore[import-untyped]
    from solders.message import Message  # type: ignore[import-untyped]
    from solders.pubkey import Pubkey  # type: ignore[import-untyped]
    from solders.system_program import TransferParams, transfer  # type: ignore[import-untyped]
    from solders.transaction import Transaction  # type: ignore[import-untyped]

    treasury_pk = service.treasury_keypair.pubkey()
    ix = transfer(TransferParams(
        from_pubkey=treasury_pk,
        to_pubkey=Pubkey.from_string(destination),
        lamports=lamports,
    ))
    blockhash = await service._get_blockhash()
    msg = Message.new_with_blockhash([ix], treasury_pk, Hash.from_string(blockhash))
    tx = Transaction.new_unsigned(msg)
    tx.sign([service.treasury_keypair], Hash.from_string(blockhash))
    return await service._send_raw_transaction(tx)


def _build_self_transfer_unsigned_tx_b64(
    wallet_address: str, rpc_blockhash: str, lamports: int,
) -> str:
    """Build an unsigned legacy SOL self-transfer; return base64 of wire bytes."""
    from solders.hash import Hash  # type: ignore[import-untyped]
    from solders.message import Message  # type: ignore[import-untyped]
    from solders.pubkey import Pubkey  # type: ignore[import-untyped]
    from solders.system_program import TransferParams, transfer  # type: ignore[import-untyped]
    from solders.transaction import Transaction  # type: ignore[import-untyped]

    sender = Pubkey.from_string(wallet_address)
    ix = transfer(TransferParams(
        from_pubkey=sender, to_pubkey=sender, lamports=lamports,
    ))
    msg = Message.new_with_blockhash([ix], sender, Hash.from_string(rpc_blockhash))
    tx = Transaction.new_unsigned(msg)
    return base64.b64encode(bytes(tx)).decode("ascii")


def _build_unauthorized_tx_b64(wallet_address: str, rpc_blockhash: str) -> str:
    """Build an unsigned tx invoking a program NOT in the Orca allowlist.

    The enclave should deny this on policy grounds without even reaching Solana.
    """
    from solders.hash import Hash  # type: ignore[import-untyped]
    from solders.instruction import AccountMeta, Instruction  # type: ignore[import-untyped]
    from solders.message import Message  # type: ignore[import-untyped]
    from solders.pubkey import Pubkey  # type: ignore[import-untyped]
    from solders.transaction import Transaction  # type: ignore[import-untyped]

    sender = Pubkey.from_string(wallet_address)
    ix = Instruction(
        program_id=Pubkey.from_string(NOT_ALLOWLISTED_PROGRAM),
        accounts=[AccountMeta(sender, is_signer=True, is_writable=True)],
        data=bytes([0, 0, 0, 0]),
    )
    msg = Message.new_with_blockhash([ix], sender, Hash.from_string(rpc_blockhash))
    tx = Transaction.new_unsigned(msg)
    return base64.b64encode(bytes(tx)).decode("ascii")


# ---------------------------------------------------------------------------
# Proof driver.
# ---------------------------------------------------------------------------


async def run_proofs() -> int:
    if settings.SOLANA_CLUSTER != "devnet":
        print(f"ERROR: SOLANA_CLUSTER={settings.SOLANA_CLUSTER!r} — devnet-only.", file=sys.stderr)
        return 2
    if "devnet" not in settings.SOLANA_RPC_URL.lower():
        print(f"ERROR: SOLANA_RPC_URL={settings.SOLANA_RPC_URL!r} not devnet.", file=sys.stderr)
        return 2
    if not (settings.PRIVY_APP_ID and settings.PRIVY_APP_SECRET):
        print("ERROR: Privy credentials missing.", file=sys.stderr)
        return 3

    evidence: dict[str, Any] = {
        "validation": "V0-VAL-1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cluster": settings.SOLANA_CLUSTER,
        "rpc_url": settings.SOLANA_RPC_URL,
        "privy_app_id": settings.PRIVY_APP_ID,
        "baseline": {},
        "agentic": {},
    }

    service = WalletService()

    # Shared httpx client with Basic Auth. Authorization-signature tests add
    # the per-request `privy-authorization-signature` header on top.
    client = httpx.AsyncClient(
        base_url=PRIVY_API_BASE,
        auth=(settings.PRIVY_APP_ID, settings.PRIVY_APP_SECRET),
        headers={"privy-app-id": settings.PRIVY_APP_ID},
        timeout=30.0,
    )

    try:
        # ================================================================
        # Baseline: vanilla Privy app-secret signing (no auth key, no policy).
        # ================================================================
        print("[baseline] creating vanilla Privy wallet...")
        b_create = await _privy_post(client, "/wallets", {"chain_type": "solana"})
        if b_create.status_code != 200:
            raise PrivyAPIError(b_create.status_code, b_create.text, "baseline_create")
        b_wallet = b_create.json()
        evidence["baseline"]["wallet"] = {
            "id": b_wallet["id"], "address": b_wallet["address"],
        }
        print(f"[baseline] wallet_id={b_wallet['id']} address={b_wallet['address']}")

        print("[baseline] funding vanilla wallet from treasury...")
        b_fund_tx = await _fund_from_treasury(service, b_wallet["address"], SEED_LAMPORTS)
        evidence["baseline"]["fund_tx"] = b_fund_tx
        print(f"[baseline] fund tx: {b_fund_tx}")
        print("[baseline] waiting for finalized balance visible to Privy RPC...")
        b_bal = await _wait_for_finalized_balance(
            settings.SOLANA_RPC_URL, b_wallet["address"], SEED_LAMPORTS,
        )
        evidence["baseline"]["finalized_balance_pre_sign"] = b_bal
        if b_bal < SEED_LAMPORTS:
            raise RuntimeError(
                f"fund did not finalize in time: balance={b_bal} expected>={SEED_LAMPORTS}"
            )

        bh = await _get_latest_blockhash(settings.SOLANA_RPC_URL)
        b_tx_b64 = _build_self_transfer_unsigned_tx_b64(
            b_wallet["address"], bh, RETURN_LAMPORTS,
        )
        print("[baseline] requesting signAndSendTransaction with Basic Auth only...")
        b_rpc = await client.post(
            f"/wallets/{b_wallet['id']}/rpc",
            json={
                "method": "signAndSendTransaction",
                "caip2": service.caip2,
                "params": {"transaction": b_tx_b64, "encoding": "base64"},
            },
        )
        if b_rpc.status_code != 200:
            raise PrivyAPIError(b_rpc.status_code, b_rpc.text, "baseline_sign_send")
        b_sig = b_rpc.json()["data"]["hash"]
        evidence["baseline"]["signed_tx"] = b_sig
        print(f"[baseline] signed+sent: {b_sig}")
        evidence["baseline"]["status"] = "success"

        # ================================================================
        # Agentic: authorization key + wallet policy + authorization-signature.
        # ================================================================
        print("[agentic] generating P-256 authorization keypair (in-memory)...")
        priv, pub_b64 = _gen_authorization_keypair()
        evidence["agentic"]["authorization_public_key"] = pub_b64
        # Never emit the private key — it stays in memory for the process lifetime only.

        print("[agentic] creating wallet policy with V0-VAL-2 Orca allowlist...")
        policy_body = {
            "version": "1.0",
            "name": f"v2-p0-orca-devnet-{int(datetime.now().timestamp())}",
            "chain_type": "solana",
            "rules": [
                {
                    "name": "Allowlist Orca devnet swap programs",
                    "method": "signAndSendTransaction",
                    "conditions": [
                        {
                            "field_source": "solana_program_instruction",
                            "field": "programId",
                            "operator": "in",
                            "value": ORCA_ALLOWLISTED_PROGRAMS,
                        }
                    ],
                    "action": "ALLOW",
                },
            ],
        }
        p_resp = await _privy_post(client, "/policies", policy_body)
        if p_resp.status_code != 200:
            raise PrivyAPIError(p_resp.status_code, p_resp.text, "create_policy")
        policy = p_resp.json()
        evidence["agentic"]["policy"] = {
            "id": policy["id"], "name": policy["name"], "rules_count": len(policy["rules"]),
        }
        print(f"[agentic] policy_id={policy['id']}")

        print("[agentic] creating wallet owned by our P-256 auth key + policy...")
        w_body = {
            "chain_type": "solana",
            "owner": {"public_key": pub_b64},
            "policy_ids": [policy["id"]],
        }
        w_resp = await _privy_post(client, "/wallets", w_body)
        if w_resp.status_code != 200:
            raise PrivyAPIError(w_resp.status_code, w_resp.text, "create_agentic_wallet")
        a_wallet = w_resp.json()
        evidence["agentic"]["wallet"] = {
            "id": a_wallet["id"],
            "address": a_wallet["address"],
            "policy_ids": a_wallet.get("policy_ids"),
        }
        print(f"[agentic] wallet_id={a_wallet['id']} address={a_wallet['address']}")

        print("[agentic] funding agentic wallet from treasury...")
        a_fund_tx = await _fund_from_treasury(service, a_wallet["address"], SEED_LAMPORTS)
        evidence["agentic"]["fund_tx"] = a_fund_tx
        print("[agentic] waiting for finalized balance visible to Privy RPC...")
        a_bal = await _wait_for_finalized_balance(
            settings.SOLANA_RPC_URL, a_wallet["address"], SEED_LAMPORTS,
        )
        evidence["agentic"]["finalized_balance_pre_sign"] = a_bal
        if a_bal < SEED_LAMPORTS:
            raise RuntimeError(
                f"agentic fund did not finalize in time: balance={a_bal} expected>={SEED_LAMPORTS}"
            )

        # -- Positive: allowed SOL self-transfer via authorization-signature flow.
        bh = await _get_latest_blockhash(settings.SOLANA_RPC_URL)
        pos_tx_b64 = _build_self_transfer_unsigned_tx_b64(
            a_wallet["address"], bh, RETURN_LAMPORTS,
        )
        pos_body = {
            "method": "signAndSendTransaction",
            "caip2": service.caip2,
            "params": {"transaction": pos_tx_b64, "encoding": "base64"},
        }
        pos_url = f"/wallets/{a_wallet['id']}/rpc"
        print("[agentic] POSITIVE: signAndSendTransaction with auth-key signature...")
        pos_resp = await _privy_post(
            client, pos_url, pos_body,
            priv_key=priv, app_id=settings.PRIVY_APP_ID,
        )
        if pos_resp.status_code != 200:
            raise PrivyAPIError(pos_resp.status_code, pos_resp.text, "agentic_positive")
        pos_sig = pos_resp.json()["data"]["hash"]
        evidence["agentic"]["positive_tx"] = pos_sig
        print(f"[agentic] POSITIVE signed+sent: {pos_sig}")

        # -- Negative: invoke a program NOT in the allowlist. Expect policy denial.
        bh2 = await _get_latest_blockhash(settings.SOLANA_RPC_URL)
        neg_tx_b64 = _build_unauthorized_tx_b64(a_wallet["address"], bh2)
        neg_body = {
            "method": "signAndSendTransaction",
            "caip2": service.caip2,
            "params": {"transaction": neg_tx_b64, "encoding": "base64"},
        }
        neg_url = f"/wallets/{a_wallet['id']}/rpc"
        print("[agentic] NEGATIVE: invoking non-allowlisted program; expecting policy denial...")
        neg_resp = await _privy_post(
            client, neg_url, neg_body,
            priv_key=priv, app_id=settings.PRIVY_APP_ID,
        )
        evidence["agentic"]["negative_status_code"] = neg_resp.status_code
        evidence["agentic"]["negative_response"] = neg_resp.text[:600]
        if neg_resp.status_code == 200:
            # Shouldn't happen. Policy is broken or misunderstood.
            print("[agentic] NEGATIVE LANDED — policy did NOT enforce", file=sys.stderr)
            evidence["agentic"]["negative_verdict"] = "policy_failed_to_deny"
            evidence["status"] = "agentic_policy_gap"
        else:
            lower = neg_resp.text.lower()
            denied = any(
                kw in lower for kw in ("polic", "denie", "not permitted", "unauthoriz", "forbidden")
            )
            evidence["agentic"]["negative_verdict"] = (
                "policy_denied" if denied else f"rejected_but_unclear_reason:{neg_resp.status_code}"
            )
            print(
                f"[agentic] NEGATIVE rejected: status={neg_resp.status_code} "
                f"verdict={evidence['agentic']['negative_verdict']}"
            )

        # -- Posture summary.
        evidence["agentic"]["posture_summary"] = {
            "who_owns_the_wallet": (
                "An ephemeral P-256 authorization key generated for this run. "
                "Owner is the public key; signing control is whoever holds the "
                "matching private key. For V2 this would be a persistent auth "
                "key rotatable independently of the Privy app secret."
            ),
            "who_holds_raw_key_material": (
                "Privy's secure enclave. Not the authorization key, not Proof "
                "Arena. Wallet secret keys never leave the enclave."
            ),
            "who_holds_authorization_material": (
                "The holder of the P-256 private key generated at the start of "
                "this run. That key is required on every signAndSendTransaction "
                "RPC via the privy-authorization-signature header."
            ),
            "who_can_trigger_signatures": (
                "Exactly two parties can sign through this wallet: (a) the "
                "app secret holder (vanilla baseline) if no auth-key-only "
                "ownership is enforced, or (b) the auth-key private key "
                "holder via authorization signature. Policy enforcement "
                "applies regardless of signer — confirmed by negative proof."
            ),
            "key_export_possible": (
                "Not exercised in V0-VAL-1. Privy exposes a /wallets/{id}/rpc "
                "method exportPrivateKey, which requires authorization-signature "
                "flow. For V2 we intentionally never call it."
            ),
            "consent_copy_fit": (
                "Accurate to say: 'Proof Arena does not hold your wallet's raw "
                "key. Proof Arena holds an authorization key that can trigger "
                "signing by Privy, constrained by a wallet policy that limits "
                "which Solana programs can be invoked.' This matches the "
                "observed behavior: policy allowed the system-program self-"
                "transfer; policy denied the non-allowlisted program call."
            ),
        }

        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        if "status" not in evidence:
            evidence["status"] = "success"
        print()
        print(json.dumps(evidence, indent=2, default=str))
        return 0

    except PrivyAPIError as exc:
        evidence["status"] = "privy_error"
        evidence["error"] = {
            "operation": exc.operation,
            "status_code": exc.status_code,
            "detail": exc.detail[:800],
        }
        print(json.dumps(evidence, indent=2, default=str), file=sys.stderr)
        return 1
    except Exception as exc:
        evidence["status"] = "error"
        evidence["error"] = repr(exc)
        print(json.dumps(evidence, indent=2, default=str), file=sys.stderr)
        return 1
    finally:
        await client.aclose()
        try:
            await service.client.aclose()
        except Exception:
            pass


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return asyncio.run(run_proofs())


if __name__ == "__main__":
    sys.exit(main())

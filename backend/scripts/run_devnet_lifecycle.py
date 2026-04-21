#!/usr/bin/env python
"""run_devnet_lifecycle.py — backend-orchestrated deterministic lifecycle proof.

Runs one complete Proof Arena V1 challenge end-to-end against the live
devnet Anchor program. DB and chain are kept synchronized by driving the
mutations through backend services/API so that RunEvent, VerificationArtifact,
and RankSnapshot rows are created alongside on-chain tx signatures.

The script is **deterministic**:
- no real Jupiter swaps,
- no real Privy wallet creation,
- two demo strategies with predetermined ending_usdc values,
- winner determined by ending_value ordering (per V1 settlement contract).

Hard guards
-----------
- devnet-only (SOLANA_CLUSTER == "devnet" AND SOLANA_RPC_URL looks like devnet).

Usage
-----
    # Inside the backend container:
    docker compose exec backend python scripts/run_devnet_lifecycle.py

Environment
-----------
    PROOF_ARENA_API_URL     (default: http://localhost:8000/api/v1)
    ADMIN_API_KEY           (required) — matches backend settings.ADMIN_API_KEY
    USER_TOKEN_1            (default: task16-user-1)
    USER_TOKEN_2            (default: task16-user-2)
    PROGRAM_ID              (required — inherited via settings)
    AUTHORITY_KEYPAIR_PATH  (required — inherited via settings)

Exit codes
----------
    0  success
    1  lifecycle failed
    2  devnet guard tripped
    3  program client unavailable
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

import httpx

from src.chain import get_program_client
from src.config import settings


logger = logging.getLogger("run_devnet_lifecycle")


DEFAULT_API_URL = "http://localhost:8000/api/v1"
WINNER_ENDING_USDC = 110_000_000  # 110 USDC (winner).
LOSER_ENDING_USDC = 95_000_000    # 95 USDC (loser).

STRATEGY_A = {
    "agent_name": "Alpha-Task16",
    "system_prompt": (
        "Execute swaps conservatively with low slippage. Prefer stable routes. "
        "Task 16 deterministic lifecycle — winner."
    ),
    "config": {
        "risk_level": "low",
        "max_slippage_bps": 50,
        "prefer_stable_routes": True,
        "swap_frequency": "low",
    },
}

STRATEGY_B = {
    "agent_name": "Beta-Task16",
    "system_prompt": (
        "Maximize ending value while staying inside challenge rules. "
        "Task 16 deterministic lifecycle — loser."
    ),
    "config": {
        "risk_level": "high",
        "max_slippage_bps": 200,
        "prefer_stable_routes": False,
        "swap_frequency": "high",
    },
}


# ---------------------------------------------------------------------------
# HTTP client factory (mockable from tests).
# ---------------------------------------------------------------------------


def make_http_client(api_url: str):
    """Return an async HTTP client context manager.

    Mockable from tests by monkeypatching this function.
    """
    return httpx.AsyncClient(base_url=api_url, timeout=60)


# ---------------------------------------------------------------------------
# Step helpers — each is a separately mockable async function.
# ---------------------------------------------------------------------------


async def register_strategy(http: Any, user_token: str, payload: dict) -> dict:
    """POST /strategies as a demo user. Returns the response body."""
    resp = await http.post(
        "/strategies",
        json=payload,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"POST /strategies failed: HTTP {resp.status_code} {resp.text}"
        )
    return resp.json()


_DEMO_OWNER_FUND_LAMPORTS = 10_000_000  # 0.01 SOL — enough to pay StrategyAccount rent.


async def _fund_demo_owner(program_client: Any, destination, lamports: int) -> str:
    """Transfer SOL from the program-client's authority wallet to a demo keypair.

    The demo owner keypair is ephemeral and starts with 0 SOL. `register_strategy`
    requires the owner to pay rent (~2.9M lamports) for the StrategyAccount PDA,
    so we top it up from the treasury here. Returns the transfer tx signature.
    """
    from solders.message import Message  # type: ignore[import-untyped]
    from solders.system_program import TransferParams, transfer  # type: ignore[import-untyped]
    from solders.transaction import Transaction as SoldersTransaction  # type: ignore[import-untyped]

    from src.services.solana_service import SolanaService

    payer = SolanaService().authority  # loads the keypair from AUTHORITY_KEYPAIR_PATH
    if payer is None:
        raise RuntimeError("Authority keypair unavailable; cannot fund demo owner.")

    ix = transfer(TransferParams(
        from_pubkey=payer.pubkey(),
        to_pubkey=destination,
        lamports=lamports,
    ))
    connection = program_client.provider.connection
    bh = (await connection.get_latest_blockhash()).value.blockhash
    msg = Message.new_with_blockhash([ix], payer.pubkey(), bh)
    tx = SoldersTransaction([payer], msg, bh)

    resp = await connection.send_raw_transaction(bytes(tx))
    sig = resp.value
    await connection.confirm_transaction(sig)
    return str(sig)


async def onchain_register_agents(
    agent_ids: list[int], program_client: Any,
) -> dict:
    """Complete on-chain strategy registration for the demo agents.

    In V1, StrategyService defers on-chain registration — the real flow signs
    with the user's Privy-embedded wallet. For Task 16's deterministic
    lifecycle we generate ephemeral owner keypairs, fund each with 0.01 SOL
    from the treasury (enough to cover StrategyAccount rent), sign
    `register_strategy` with the demo keypair, and update the Postgres Agent
    row via `complete_onchain_registration()`. The keypairs are NOT stored.
    """
    from solders.keypair import Keypair  # type: ignore[import-untyped]
    from sqlalchemy import select

    from src.db.engine import async_session_factory
    from src.db.models import Agent
    from src.services.strategy_service import StrategyService

    results: dict = {"register_txs": {}, "fund_txs": {}}

    async with async_session_factory() as session:
        agents = (
            await session.execute(
                select(Agent).where(Agent.agent_id.in_(agent_ids)).order_by(Agent.agent_id)
            )
        ).scalars().all()

        svc = StrategyService(session)

        for agent in agents:
            owner_kp = Keypair()
            submission_hash_bytes = bytes.fromhex(agent.submission_hash)

            # Step 1: fund the demo owner so it can pay rent.
            try:
                fund_sig = await _fund_demo_owner(
                    program_client, owner_kp.pubkey(), _DEMO_OWNER_FUND_LAMPORTS,
                )
                results["fund_txs"][str(agent.agent_id)] = fund_sig
            except Exception as exc:
                raise RuntimeError(
                    f"Funding demo owner for agent {agent.agent_id} failed: {exc}"
                ) from exc

            # Step 2: sign and submit register_strategy with the demo keypair.
            try:
                tx_sig, strategy_pda = await program_client.register_strategy(
                    agent_id=agent.agent_id,
                    agent_name=agent.display_name[:64],
                    submission_hash=submission_hash_bytes,
                    metadata_ref="task16-deterministic",
                    owner_keypair=owner_kp,
                )
            except Exception as exc:
                agent.status = "onchain_failed"
                await session.commit()
                raise RuntimeError(
                    f"On-chain register_strategy failed for agent "
                    f"{agent.agent_id}: {exc}"
                ) from exc

            await svc.complete_onchain_registration(
                agent_id=agent.agent_id,
                onchain_address=str(strategy_pda),
                tx_signature=str(tx_sig),
            )
            results["register_txs"][str(agent.agent_id)] = str(tx_sig)

    return results


async def create_challenge_via_api(
    http: Any, admin_api_key: str, contestant_agent_ids: list[int],
) -> dict:
    """POST /admin/challenges. Returns the response body including challenge_id."""
    body = {
        "challenge_type": "swap_execution",
        "starting_usdc": 100_000_000,
        "swap_intents": ["SOL"],
        "allowed_routes": [],
        "max_slippage_bps": 100,
        "iteration_budget": 20,
        "time_budget_secs": 300,
        "llm_provider": "anthropic",
        "llm_model": "claude-sonnet-4-20250514",
        "contestant_agent_ids": contestant_agent_ids,
    }
    resp = await http.post(
        "/admin/challenges",
        json=body,
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"POST /admin/challenges failed: HTTP {resp.status_code} {resp.text}"
        )
    return resp.json()


async def start_challenge_via_api(http: Any, admin_api_key: str, challenge_id: int) -> dict:
    """POST /admin/challenges/{id}/start."""
    resp = await http.post(
        f"/admin/challenges/{challenge_id}/start",
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"POST /admin/challenges/{challenge_id}/start failed: "
            f"HTTP {resp.status_code} {resp.text}"
        )
    return resp.json()


async def deterministic_finalize_runs(
    challenge_id: int,
    winner_agent_id: int,
    winner_ending: int,
    loser_agent_id: int,
    loser_ending: int,
    program_client: Any,
) -> dict:
    """Finalize both runs with deterministic ending values.

    Writes a minimal event sequence into Postgres per run (observe/decide/
    execute/finalize), computes run_log_hash, calls program.finalize_run on
    chain, updates the Run row, and returns the tx signatures.

    The caller must have already created the Runs (via the create_challenge
    HTTP flow); this helper only finalizes them.
    """
    from sqlalchemy import select

    from src.db.engine import async_session_factory
    from src.db.models import Challenge, Run, RunEvent
    from src.integrity.run_auditor import compute_evidence_hash

    results = {"finalize_txs": {}}

    async with async_session_factory() as session:
        challenge = (
            await session.execute(
                select(Challenge).where(Challenge.challenge_id == challenge_id)
            )
        ).scalar_one()

        runs = (
            await session.execute(
                select(Run).where(Run.challenge_id == challenge_id).order_by(Run.run_id)
            )
        ).scalars().all()

        for run in runs:
            if run.agent_id == winner_agent_id:
                ending_value = winner_ending
                completion_variant = "Complete"
                completion_status = "complete"
            elif run.agent_id == loser_agent_id:
                ending_value = loser_ending
                completion_variant = "Complete"
                completion_status = "complete"
            else:
                continue

            now = datetime.now(timezone.utc)
            # Deterministic minimal event sequence covered by run_log_hash.
            events_for_hash = [
                {"sequence_no": 1, "event_type": "observe", "state": {"balances": {"USDC": 100_000_000}}},
                {"sequence_no": 2, "event_type": "decide", "action": {"type": "EXECUTE_SWAP"}},
                {
                    "sequence_no": 3,
                    "event_type": "execute",
                    "result": {"ending_usdc_estimate": ending_value},
                },
                {
                    "sequence_no": 4,
                    "event_type": "finalize",
                    "result": {
                        "ending_value": ending_value,
                        "completion_status": completion_status,
                    },
                },
            ]

            for evt in events_for_hash:
                session.add(RunEvent(
                    run_id=run.run_id,
                    sequence_no=evt["sequence_no"],
                    event_type=evt["event_type"],
                    timestamp=now,
                    state_snapshot_json=json.dumps(evt.get("state", {})),
                    action_payload_json=json.dumps(evt.get("action", {})),
                    result_payload_json=json.dumps(evt.get("result", {})),
                ))

            # Hash boundary: over the canonical event payload list.
            run.run_log_hash = compute_evidence_hash(events_for_hash)
            run.ending_value = ending_value
            run.completion_status = completion_status
            run.iterations_used = 1
            run.score_inputs_json = json.dumps({
                "completed_required_actions": True,
                "completion_rate": 1.0,
                "invalid_run": False,
                "execution_quality": ending_value / (run.starting_value or 1),
                "ending_value_delta": ending_value - (run.starting_value or 0),
                "iterations_used": 1,
                "time_used_secs": 1,
            })
            run.ended_at = now

            # On-chain finalize
            try:
                tx_sig = await program_client.finalize_run(
                    challenge_id=run.challenge_id,
                    agent_id=run.agent_id,
                    ending_usdc=ending_value,
                    run_log_hash=bytes.fromhex(run.run_log_hash),
                    completion_status_variant=completion_variant,
                    iterations_used=1,
                )
            except Exception as exc:
                run.status = "onchain_failed"
                await session.commit()
                raise RuntimeError(
                    f"On-chain finalize_run failed for agent {run.agent_id}: {exc}"
                ) from exc

            # Post-chain operational event (OUTSIDE hash boundary).
            session.add(RunEvent(
                run_id=run.run_id,
                sequence_no=5,
                event_type="onchain_finalize",
                timestamp=now,
                result_payload_json=json.dumps({
                    "tx_signature": str(tx_sig),
                    "run_log_hash": run.run_log_hash,
                }),
                tx_signature=str(tx_sig),
            ))

            run.status = "completed"
            challenge.num_finalized = (challenge.num_finalized or 0) + 1
            results["finalize_txs"][str(run.agent_id)] = str(tx_sig)

        await session.commit()

    return results


async def settle_via_service(challenge_id: int, program_client: Any) -> dict:
    """Call SettlementService.settle_challenge(). Returns summary of tx signatures."""
    from src.db.engine import async_session_factory
    from src.services.settlement_service import SettlementService

    async with async_session_factory() as session:
        svc = SettlementService(session, program_client=program_client)
        challenge = await svc.settle_challenge(challenge_id)

    # SettlementService writes VerificationArtifact rows with the tx signatures;
    # we extract them for the summary.
    from sqlalchemy import select

    from src.db.models import VerificationArtifact, RankSnapshot, Run

    async with async_session_factory() as session:
        run_ids = (
            await session.execute(
                select(Run.run_id).where(Run.challenge_id == challenge_id)
            )
        ).scalars().all()

        artifacts = (
            await session.execute(
                select(VerificationArtifact).where(
                    VerificationArtifact.run_id.in_(run_ids),
                )
            )
        ).scalars().all()

        settle_tx = next(
            (a.uri_or_ref for a in artifacts if a.artifact_type == "onchain_settle"),
            None,
        )

        rank_snaps = (
            await session.execute(
                select(RankSnapshot).order_by(RankSnapshot.computed_at.desc()).limit(10)
            )
        ).scalars().all()

    return {
        "settle_tx": settle_tx,
        "winner_agent_id": challenge.winner_agent_id,
        "rank_snapshots_created": len(rank_snaps),
    }


async def verify_leaderboard(http: Any) -> bool:
    """GET /leaderboard — return True if the list contains at least one entry with wins>=1."""
    resp = await http.get("/leaderboard")
    if resp.status_code >= 400:
        return False
    entries = resp.json()
    return isinstance(entries, list) and any(
        (entry.get("wins") or 0) >= 1 for entry in entries
    )


async def verify_challenge_detail(http: Any, challenge_id: int) -> bool:
    """GET /challenges/{id} — return True if status=='completed' and winner_agent_id is set."""
    resp = await http.get(f"/challenges/{challenge_id}")
    if resp.status_code >= 400:
        return False
    body = resp.json()
    return body.get("status") == "completed" and body.get("winner_agent_id") is not None


async def verify_agent_profile(http: Any, agent_id: int) -> bool:
    """GET /agents/{id} — return True if the profile returns 200."""
    resp = await http.get(f"/agents/{agent_id}")
    return resp.status_code == 200


# ---------------------------------------------------------------------------
# Orchestration entrypoint.
# ---------------------------------------------------------------------------


async def orchestrate(
    api_url: str, admin_api_key: str, user_tokens: list[str],
) -> dict:
    """Run the full lifecycle. Returns the structured JSON summary."""
    program_client = get_program_client()
    if program_client is None:
        raise RuntimeError(
            "Program client unavailable. Cannot run a live-chain lifecycle."
        )

    tx_signatures: dict[str, Any] = {}
    api_verification: dict[str, bool] = {}

    async with make_http_client(api_url) as http:
        # Step 2: register two strategies in Postgres (on-chain deferred).
        r_alpha = await register_strategy(http, user_tokens[0], STRATEGY_A)
        r_beta = await register_strategy(http, user_tokens[1], STRATEGY_B)
        agent_alpha = r_alpha["agent_id"]
        agent_beta = r_beta["agent_id"]

        # Step 2b: complete on-chain strategy registration with demo keypairs.
        # Without this, agents stay `pending_onchain` and ChallengeService
        # skips on-chain create_run → finalize_run would have no RunAccount.
        reg = await onchain_register_agents(
            [agent_alpha, agent_beta], program_client,
        )
        tx_signatures["register_strategy"] = reg["register_txs"]

        # Step 3: create challenge (now on-chain create_run fires per agent).
        create_resp = await create_challenge_via_api(
            http, admin_api_key, [agent_alpha, agent_beta],
        )
        challenge_id = create_resp["challenge_id"]
        tx_signatures["create_challenge"] = create_resp.get(
            "onchain_txs", {}
        ).get("create_challenge")
        tx_signatures["create_run"] = create_resp.get("onchain_txs", {}).get("create_run", [])

        # Step 4: start challenge.
        start_resp = await start_challenge_via_api(http, admin_api_key, challenge_id)
        tx_signatures["start_challenge"] = start_resp.get("onchain_tx")

        # Step 5: deterministic finalize via direct backend service.
        fin = await deterministic_finalize_runs(
            challenge_id=challenge_id,
            winner_agent_id=agent_alpha,
            winner_ending=WINNER_ENDING_USDC,
            loser_agent_id=agent_beta,
            loser_ending=LOSER_ENDING_USDC,
            program_client=program_client,
        )
        tx_signatures["finalize_run"] = fin["finalize_txs"]

        # Step 6: settle.
        settle = await settle_via_service(challenge_id, program_client)
        tx_signatures["settle_challenge"] = settle["settle_tx"]

        # Step 7: API read-model verification.
        api_verification["leaderboard_ok"] = await verify_leaderboard(http)
        api_verification["challenge_detail_ok"] = await verify_challenge_detail(
            http, challenge_id,
        )
        profile_a = await verify_agent_profile(http, agent_alpha)
        profile_b = await verify_agent_profile(http, agent_beta)
        api_verification["agent_profile_ok"] = profile_a and profile_b

    summary = {
        "challenge_id": challenge_id,
        "winner_agent_id": settle.get("winner_agent_id"),
        "tx_signatures": tx_signatures,
        "api_verification": api_verification,
        "deferred": {
            "real_jupiter_swap_execution": True,
            "real_privy_wallet_creation": True,
        },
    }
    # Emit structured JSON on its own line so operators / CI can grep for it.
    print(json.dumps(summary))
    return summary


# ---------------------------------------------------------------------------
# Devnet guard + entrypoint.
# ---------------------------------------------------------------------------


async def main_async(api_url: str, admin_api_key: str, user_tokens: list[str]) -> int:
    if settings.SOLANA_CLUSTER != "devnet":
        print(
            f"ERROR: SOLANA_CLUSTER={settings.SOLANA_CLUSTER!r} — lifecycle "
            f"script is devnet-only. Refusing to run.",
            file=sys.stderr,
        )
        return 2
    if "devnet" not in settings.SOLANA_RPC_URL.lower():
        print(
            f"ERROR: SOLANA_RPC_URL={settings.SOLANA_RPC_URL!r} does not look "
            f"like a devnet RPC. Refusing to run.",
            file=sys.stderr,
        )
        return 2

    try:
        await orchestrate(api_url, admin_api_key, user_tokens)
        return 0
    except Exception as exc:
        logger.exception("Lifecycle failed")
        print(f"run_devnet_lifecycle: FAILED err={exc!r}", file=sys.stderr)
        return 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_devnet_lifecycle.py",
        description=(
            "Backend-orchestrated deterministic lifecycle against the live "
            "Proof Arena devnet program. Keeps Postgres and chain synchronized. "
            "Devnet-only."
        ),
        epilog=(
            "Environment:\n"
            "  PROOF_ARENA_API_URL    (default: http://localhost:8000/api/v1)\n"
            "  ADMIN_API_KEY          (required)\n"
            "  USER_TOKEN_1           (default: task16-user-1)\n"
            "  USER_TOKEN_2           (default: task16-user-2)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("PROOF_ARENA_API_URL", DEFAULT_API_URL),
        help="Backend API base URL (PROOF_ARENA_API_URL).",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args()

    admin_api_key = os.environ.get("ADMIN_API_KEY") or settings.ADMIN_API_KEY
    if not admin_api_key:
        print("ERROR: ADMIN_API_KEY not set.", file=sys.stderr)
        return 4

    user_tokens = [
        os.environ.get("USER_TOKEN_1", "task16-user-1"),
        os.environ.get("USER_TOKEN_2", "task16-user-2"),
    ]

    return asyncio.run(main_async(args.api_url, admin_api_key, user_tokens))


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
"""Proof Arena — end-to-end demo script.

Submits 2 strategies, creates a challenge, starts it, polls status until
completion, and prints the settlement result + leaderboard.

REQUIRES a running Proof Arena backend + Postgres. Does not start services.

USAGE
    python scripts/run_demo.py [--help]

ENV VARS
    PROOF_ARENA_API_URL  (default: http://localhost:8000/api/v1)
    ADMIN_API_KEY        (required) — matches backend settings.ADMIN_API_KEY
    USER_TOKEN_1         (required) — bearer token used as user identity for strategy 1
    USER_TOKEN_2         (required) — bearer token used as user identity for strategy 2
    FRONTEND_URL         (default: http://localhost:3000)
    POLL_TIMEOUT_SECS    (default: 300)

NOTES
    - In V1 the bearer token is the user identity placeholder, not a real
      Privy JWT. Use distinct values per user so the anti-spam counter
      treats them independently.
    - This script does NOT claim on-chain success unless the backend surfaces
      a tx signature. It prints the local challenge/agent IDs + frontend
      URLs a judge can open directly.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

import httpx

DEFAULT_API_URL = "http://localhost:8000/api/v1"
DEFAULT_FRONTEND_URL = "http://localhost:3000"
DEFAULT_POLL_TIMEOUT = 300

STRATEGY_A = {
    "agent_name": "Conservative Trader",
    "system_prompt": (
        "Execute swaps conservatively with low slippage. Prefer stable routes. "
        "Minimize unnecessary swaps. Prioritize capital preservation while "
        "completing the required basket."
    ),
    "config": {
        "risk_level": "low",
        "max_slippage_bps": 50,
        "prefer_stable_routes": True,
        "swap_frequency": "low",
    },
}

STRATEGY_B = {
    "agent_name": "Aggressive Trader",
    "system_prompt": (
        "Maximize ending value while staying inside the challenge rules. "
        "Accept higher allowed slippage when justified by available quotes. "
        "Complete required swaps efficiently."
    ),
    "config": {
        "risk_level": "high",
        "max_slippage_bps": 200,
        "prefer_stable_routes": False,
        "swap_frequency": "high",
    },
}


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _env_or_die(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        _die(f"Missing required env var: {name}")
    return v


async def _safe_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    **kwargs: Any,
) -> httpx.Response:
    try:
        resp = await client.request(method, path, **kwargs)
    except httpx.ConnectError as e:
        _die(f"Cannot connect to backend at {client.base_url}: {e}")
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        _die(
            f"{method} {path} returned {resp.status_code}: {detail}",
            code=2,
        )
    return resp


async def run_demo(api_url: str, frontend_url: str, timeout_secs: int) -> None:
    admin_key = _env_or_die("ADMIN_API_KEY")
    user_token_a = _env_or_die("USER_TOKEN_1")
    user_token_b = _env_or_die("USER_TOKEN_2")

    print("=== Proof Arena — Demo ===\n")
    print(f"Backend API:  {api_url}")
    print(f"Frontend:     {frontend_url}\n")

    async with httpx.AsyncClient(base_url=api_url, timeout=60) as client:
        # 1. Submit strategies
        print("1. Submitting strategies...")
        r1 = await _safe_request(
            client, "POST", "/strategies",
            json=STRATEGY_A,
            headers={"Authorization": f"Bearer {user_token_a}"},
        )
        agent_a = r1.json()
        print(
            f"   Alpha  agent_id={agent_a['agent_id']}  "
            f"hash={agent_a['submission_hash'][:16]}..."
        )

        r2 = await _safe_request(
            client, "POST", "/strategies",
            json=STRATEGY_B,
            headers={"Authorization": f"Bearer {user_token_b}"},
        )
        agent_b = r2.json()
        print(
            f"   Beta   agent_id={agent_b['agent_id']}  "
            f"hash={agent_b['submission_hash'][:16]}...\n"
        )

        # 2. Create challenge (admin)
        print("2. Creating challenge...")
        challenge_req = {
            "challenge_type": "swap_execution",
            "starting_usdc": 100_000_000,  # 100 USDC
            "swap_intents": ["SOL"],
            "allowed_routes": [],
            "max_slippage_bps": 100,
            "iteration_budget": 20,
            "time_budget_secs": 300,
            "llm_provider": "anthropic",
            "llm_model": "claude-sonnet-4-20250514",
            "contestant_agent_ids": [agent_a["agent_id"], agent_b["agent_id"]],
        }
        cr = await _safe_request(
            client, "POST", "/admin/challenges",
            json=challenge_req,
            headers={"Authorization": f"Bearer {admin_key}"},
        )
        challenge = cr.json()
        challenge_id = challenge["challenge_id"]
        print(f"   challenge_id={challenge_id}  status={challenge['status']}\n")

        # 3. Start challenge
        print("3. Starting challenge...")
        sr = await _safe_request(
            client, "POST", f"/admin/challenges/{challenge_id}/start",
            headers={"Authorization": f"Bearer {admin_key}"},
        )
        print(f"   status={sr.json()['status']}\n")

        # 4. Poll
        print(f"4. Polling challenge (timeout {timeout_secs}s)...")
        deadline = asyncio.get_event_loop().time() + timeout_secs
        last_status = None
        while asyncio.get_event_loop().time() < deadline:
            try:
                status_resp = await client.get(f"/challenges/{challenge_id}")
                if status_resp.status_code != 200:
                    print(f"   WARN: poll returned {status_resp.status_code}")
                    await asyncio.sleep(5)
                    continue
                data = status_resp.json()
            except httpx.RequestError as e:
                print(f"   WARN: poll error: {e}")
                await asyncio.sleep(5)
                continue

            if data["status"] != last_status:
                last_status = data["status"]
                print(
                    f"   status={data['status']}  "
                    f"finalized={data['num_finalized']}/{data['num_contestants']}"
                )
            if data["status"] == "completed":
                break
            await asyncio.sleep(5)
        else:
            _die(f"Challenge did not complete within {timeout_secs}s")

        # 5. Settlement result
        print("\n5. Settlement")
        winner_id = data.get("winner_agent_id")
        if winner_id is None:
            print("   No eligible winner (all runs ineligible)")
        else:
            print(f"   winner_agent_id={winner_id}")
            for c in data.get("contestants", []):
                marker = "  <-- WINNER" if c["agent_id"] == winner_id else ""
                ending = c.get("ending_value")
                ending_str = f"{ending / 1_000_000:.2f} USDC" if ending is not None else "—"
                print(
                    f"   - {c['display_name']:30}  "
                    f"status={c['status']:10}  "
                    f"completion={c.get('completion_status') or '—':11}  "
                    f"ending={ending_str}{marker}"
                )

        # 6. Leaderboard
        print("\n6. Leaderboard (top 5)")
        lb_resp = await _safe_request(client, "GET", "/leaderboard", params={"limit": 5})
        for i, entry in enumerate(lb_resp.json(), 1):
            print(
                f"   #{i}  {entry['display_name']:30}  "
                f"score={entry['score']:6.2f}  "
                f"{entry['wins']}W/{entry['losses']}L  "
                f"({entry['rank_version']})"
            )

        # 7. Frontend URLs
        print("\n=== Demo complete ===")
        print(f"Challenge:   {frontend_url}/challenges/{challenge_id}")
        print(f"Leaderboard: {frontend_url}/leaderboard")
        if winner_id is not None:
            print(f"Winner:      {frontend_url}/agents/{winner_id}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Proof Arena end-to-end demo.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("PROOF_ARENA_API_URL", DEFAULT_API_URL),
        help=f"Backend API base URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--frontend-url",
        default=os.environ.get("FRONTEND_URL", DEFAULT_FRONTEND_URL),
        help=f"Frontend URL for links (default: {DEFAULT_FRONTEND_URL})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("POLL_TIMEOUT_SECS", DEFAULT_POLL_TIMEOUT)),
        help=f"Challenge poll timeout in seconds (default: {DEFAULT_POLL_TIMEOUT})",
    )
    args = parser.parse_args()
    asyncio.run(run_demo(args.api_url, args.frontend_url, args.timeout))


if __name__ == "__main__":
    main()

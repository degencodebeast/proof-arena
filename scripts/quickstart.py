#!/usr/bin/env python
"""Proof Arena — Python Quickstart

Educational example showing V1 API-driven strategy submission.

V1 MODEL
    You submit a STRATEGY (system_prompt + config). Proof Arena runs it
    inside a controlled benchmark executor (LocalAgentProvider). You do NOT
    deploy or host an agent — the arena runs your strategy for you in
    identical conditions against others.

    This is NOT arbitrary external live-agent runtime. Framework-specific
    quickstarts (Mastra, Eliza, Vercel AI SDK, Agno) are out of V1 scope.

USAGE
    python scripts/quickstart.py [--help]

ENV VARS
    PROOF_ARENA_API_URL  (default: http://localhost:8000/api/v1)
    USER_TOKEN           (required) — bearer token used as user identity
    CHALLENGE_ID         (optional) — if set, quickstart fetches challenge detail
    AGENT_ID             (optional) — if set, quickstart fetches agent profile

WHAT THIS SCRIPT DEMONSTRATES
    1. POST /api/v1/strategies      — submit a strategy
    2. GET  /api/v1/challenges/{id} — inspect a challenge (optional)
    3. GET  /api/v1/leaderboard     — read the leaderboard
    4. GET  /api/v1/agents/{id}     — read an agent profile (optional)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx

DEFAULT_API_URL = "http://localhost:8000/api/v1"

EXAMPLE_STRATEGY = {
    "agent_name": "Quickstart Bot",
    "system_prompt": (
        "You are a swap execution agent for DeFi benchmarks.\n"
        "Available actions (respond with JSON only):\n"
        "  - {\"type\": \"EXECUTE_SWAP\", \"params\": {\"quote_id\": \"<id>\", "
        "\"max_slippage_bps\": <0-500>}}\n"
        "  - {\"type\": \"WAIT\", \"params\": {\"seconds\": <1-60>}}\n"
        "  - {\"type\": \"FINISH\", \"params\": {}}\n"
        "Complete the required swaps efficiently. Prioritize execution quality."
    ),
    "config": {"strategy_version": "quickstart-1.0"},
}


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _handle_error(resp: httpx.Response, hint: str = "") -> None:
    if resp.status_code >= 400:
        detail = ""
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        _die(f"{hint}HTTP {resp.status_code}: {detail}")


async def submit_strategy(client: httpx.AsyncClient, user_token: str) -> dict:
    """1) POST /strategies — register a new strategy under your user token."""
    print("=" * 60)
    print("1) Submit a strategy — POST /api/v1/strategies")
    print("=" * 60)
    print(f"   agent_name:    {EXAMPLE_STRATEGY['agent_name']}")
    print(f"   system_prompt: {len(EXAMPLE_STRATEGY['system_prompt'])} chars")
    print(f"   config:        {EXAMPLE_STRATEGY['config']}")

    try:
        resp = await client.post(
            "/strategies",
            json=EXAMPLE_STRATEGY,
            headers={"Authorization": f"Bearer {user_token}"},
        )
    except httpx.ConnectError as e:
        _die(f"Cannot connect to backend at {client.base_url}: {e}")

    _handle_error(resp, hint="submit_strategy: ")
    data = resp.json()
    print("\n   Response (StrategyResponse):")
    print(f"   - agent_id:        {data['agent_id']}")
    print(f"   - display_name:    {data['display_name']}")
    print(f"   - submission_hash: {data['submission_hash']}")
    print(f"   - onchain_address: {data.get('onchain_address') or 'pending'}")
    return data


async def check_challenge(client: httpx.AsyncClient, challenge_id: int) -> None:
    """2) GET /challenges/{id} — inspect challenge state + contestants."""
    print("\n" + "=" * 60)
    print(f"2) Check challenge — GET /api/v1/challenges/{challenge_id}")
    print("=" * 60)
    try:
        resp = await client.get(f"/challenges/{challenge_id}")
    except httpx.ConnectError as e:
        _die(f"Cannot connect: {e}")
    if resp.status_code == 404:
        print(f"   Challenge {challenge_id} not found.")
        return
    _handle_error(resp, hint="check_challenge: ")
    data = resp.json()
    print(f"   status:           {data['status']}")
    print(f"   challenge_type:   {data['challenge_type']}")
    print(f"   contestants:      {data['num_finalized']}/{data['num_contestants']} finalized")
    print(f"   winner_agent_id:  {data.get('winner_agent_id') or 'pending'}")
    for c in data.get("contestants", []):
        ending = c.get("ending_value")
        ending_str = f"{ending / 1_000_000:.2f} USDC" if ending is not None else "—"
        print(
            f"     - agent_id={c['agent_id']:4}  {c['display_name']:30}  "
            f"status={c['status']:10}  ending={ending_str}"
        )


async def read_leaderboard(client: httpx.AsyncClient) -> None:
    """3) GET /leaderboard — read current ranked agents."""
    print("\n" + "=" * 60)
    print("3) Read leaderboard — GET /api/v1/leaderboard?limit=10")
    print("=" * 60)
    try:
        resp = await client.get("/leaderboard", params={"limit": 10})
    except httpx.ConnectError as e:
        _die(f"Cannot connect: {e}")
    _handle_error(resp, hint="read_leaderboard: ")
    entries = resp.json()
    if not entries:
        print("   (leaderboard is empty — no ranked agents yet)")
        return
    for i, entry in enumerate(entries, 1):
        print(
            f"   #{i}  {entry['display_name']:30}  "
            f"score={entry['score']:6.2f}  "
            f"{entry['wins']}W/{entry['losses']}L  "
            f"({entry['rank_version']})"
        )


async def read_agent_profile(client: httpx.AsyncClient, agent_id: int) -> None:
    """4) GET /agents/{id} — read agent profile + recent runs."""
    print("\n" + "=" * 60)
    print(f"4) Read agent profile — GET /api/v1/agents/{agent_id}")
    print("=" * 60)
    try:
        resp = await client.get(f"/agents/{agent_id}")
    except httpx.ConnectError as e:
        _die(f"Cannot connect: {e}")
    if resp.status_code == 404:
        print(f"   Agent {agent_id} not found.")
        return
    _handle_error(resp, hint="read_agent_profile: ")
    data = resp.json()
    print(f"   agent_id:         {data['agent_id']}")
    print(f"   display_name:     {data['display_name']}")
    print(f"   owner_wallet:     {data['owner_wallet']}")
    print(f"   submission_hash:  {data['submission_hash']}")
    rank = data.get("current_rank")
    if rank:
        print(f"   current_rank:     score={rank['score']:.2f}  {rank['wins']}W/{rank['losses']}L")
    else:
        print("   current_rank:     (none yet)")
    runs = data.get("recent_runs", [])
    print(f"   recent_runs:      {len(runs)}")
    for r in runs[:5]:
        print(
            f"     - challenge={r['challenge_id']}  "
            f"status={r['status']}  "
            f"completion={r.get('completion_status') or '—'}"
        )


async def main(api_url: str) -> None:
    print("Proof Arena — Python Quickstart\n")
    print("V1 Model: Submit a strategy (prompt + config). Proof Arena runs")
    print("it in a controlled benchmark. You read results.\n")
    print("This is NOT arbitrary external live-agent runtime.\n")
    print(f"API base: {api_url}\n")

    user_token = os.environ.get("USER_TOKEN")
    if not user_token:
        _die("Missing required env var: USER_TOKEN")

    challenge_id_env = os.environ.get("CHALLENGE_ID")
    agent_id_env = os.environ.get("AGENT_ID")

    async with httpx.AsyncClient(base_url=api_url, timeout=30) as client:
        submitted = await submit_strategy(client, user_token)

        if challenge_id_env:
            try:
                await check_challenge(client, int(challenge_id_env))
            except ValueError:
                print(f"\n   WARN: CHALLENGE_ID={challenge_id_env} is not an int; skipping")

        await read_leaderboard(client)

        target_agent = agent_id_env or submitted.get("agent_id")
        if target_agent:
            try:
                await read_agent_profile(client, int(target_agent))
            except ValueError:
                print(f"\n   WARN: AGENT_ID={target_agent} is not an int; skipping")

    print("\n" + "=" * 60)
    print("Next steps")
    print("=" * 60)
    print("  - Watch /api/v1/leaderboard as challenges complete.")
    print("  - Inspect /api/v1/challenges/{id}/events for a run's evidence trail.")
    print("  - Framework-specific quickstarts are NOT in V1. The API itself IS the surface.")


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="Proof Arena Python quickstart",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("PROOF_ARENA_API_URL", DEFAULT_API_URL),
        help=f"Backend API base URL (default: {DEFAULT_API_URL})",
    )
    args = parser.parse_args()
    asyncio.run(main(args.api_url))


if __name__ == "__main__":
    cli()

"""AgentOS canonical-agent smoke test (operator-run).

Validates the legacy single-agent env-pair contract and the Task 12
deploy-time invariants without exercising the wallet/Orca path.
Read-only by default; pass ``--create-session`` to additionally
exercise session creation.

Scope: this script covers the legacy ``AGENTOS_CANONICAL_AGENT_ID``
(single-template) path only. Multi-template dispatch via
``AGENTOS_CANONICAL_AGENT_IDS_JSON`` is handled at backend runtime
construction by ``get_canonical_agent_ids()`` in
``backend/src/config.py``. Adding multi-template smoke validation is a
future operator-tool enhancement.

Required env:
- ``AGENTOS_API_URL``      — e.g. ``http://agentos:7000`` (Coolify
                              private DNS) or ``https://...`` if
                              publicly exposed.
- ``AGENTOS_CANONICAL_AGENT_ID`` — legacy single-template back-compat.
                                    Must equal the agent id the AgentOS
                                    process declared at startup. Default
                                    ``swap_executor_v1``. For multi-
                                    template deploys (swap + rebalance),
                                    use ``AGENTOS_CANONICAL_AGENT_IDS_JSON``
                                    instead (a JSON dict keyed by
                                    template_key, e.g.
                                    ``{"swap_executor_v1": "...",
                                    "rebalance_executor_v1": "..."}``).

Optional env:
- ``AGENTOS_AUTH_TOKEN``   — Bearer JWT, required only if AgentOS is
                              configured to require auth.

Exit codes:
- ``0`` — all checks pass.
- ``2`` — env config error (missing required env).
- ``3`` — health/config endpoint unreachable.
- ``4`` — canonical agent id mismatch (drift).
- ``5`` — session creation failed (only when --create-session).

Examples (operator workflow):
    AGENTOS_API_URL=http://agentos:7000 \\
    AGENTOS_CANONICAL_AGENT_ID=swap_executor_v1 \\
    python -m agentos_app.scripts.smoke
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentos_app.scripts.smoke",
        description=(
            "AgentOS canonical-agent smoke test. Validates the legacy "
            "single-agent AGENTOS_CANONICAL_AGENT_ID env-pair contract. "
            "Multi-template (AGENTOS_CANONICAL_AGENT_IDS_JSON) is handled "
            "by backend runtime construction; multi-template smoke is a "
            "future enhancement."
        ),
    )
    p.add_argument(
        "--create-session",
        action="store_true",
        help=(
            "Additionally create an AgentOS session against the "
            "canonical agent. Off by default — read-only smoke."
        ),
    )
    p.add_argument(
        "--user-id",
        default="smoke-test-user",
        help="user_id passed to create_session when --create-session is set",
    )
    return p


def _require_env(name: str) -> str:
    v = os.environ.get(name, "")
    if not v:
        sys.stderr.write(
            f"smoke: env {name!r} is required and was empty\n"
        )
        sys.exit(2)
    return v


async def _run_async(create_session: bool, user_id: str) -> int:
    from agno.client import AgentOSClient  # smoke is the OPS boundary;
    # importing here keeps unit tests free of the SDK dependency.

    api_url = _require_env("AGENTOS_API_URL")
    expected_agent_id = _require_env("AGENTOS_CANONICAL_AGENT_ID")
    auth_token = os.environ.get("AGENTOS_AUTH_TOKEN", "")
    headers = (
        {"Authorization": f"Bearer {auth_token}"} if auth_token else None
    )

    client = AgentOSClient(base_url=api_url)

    # Step 1: hit /config (or equivalent) and parse the agent list.
    try:
        config = await client.aget_config(headers=headers)
    except Exception as exc:  # noqa: BLE001 — smoke surfaces all faults
        sys.stderr.write(
            f"smoke: cannot reach AgentOS at {api_url!r}: {exc}\n"
        )
        return 3

    agent_ids = _extract_agent_ids(config)
    print(f"smoke: AgentOS at {api_url} declares agents: {sorted(agent_ids)}")

    if expected_agent_id not in agent_ids:
        sys.stderr.write(
            f"smoke: ENV-PAIR DRIFT — backend AGENTOS_CANONICAL_AGENT_ID="
            f"{expected_agent_id!r} not found in AgentOS-declared agents "
            f"{sorted(agent_ids)}. Fix: align "
            f"agent-rank/agentos_app/config.py canonical_agent_id with the "
            f"backend env, then redeploy AgentOS.\n"
        )
        return 4

    print(
        f"smoke: env-pair contract OK — {expected_agent_id} declared "
        f"by AgentOS and matches backend env."
    )

    if not create_session:
        return 0

    # Step 2 (opt-in): create a session.
    try:
        session = await client.create_session(
            agent_id=expected_agent_id,
            user_id=user_id,
            session_name="smoke-test-session",
            headers=headers,
        )
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"smoke: create_session failed: {exc}\n")
        return 5

    sid = getattr(session, "session_id", None) or session.get("session_id")
    print(f"smoke: session created OK — session_id={sid}")
    return 0


def _extract_agent_ids(config: Any) -> set[str]:
    """Best-effort extraction of agent ids from AgentOS /config response.

    Agno's response shape is documented as a dict-or-pydantic with an
    ``agents`` field that is a list of ``{id: ..., name: ...}``-shaped
    items. This helper normalizes both shapes.
    """
    if hasattr(config, "agents"):
        agents = config.agents
    elif isinstance(config, dict):
        agents = config.get("agents", [])
    else:
        agents = []

    ids: set[str] = set()
    for a in agents or []:
        if hasattr(a, "id"):
            ids.add(str(a.id))
        elif isinstance(a, dict) and "id" in a:
            ids.add(str(a["id"]))
    return ids


def main() -> int:
    args = _build_parser().parse_args()
    return asyncio.run(
        _run_async(
            create_session=args.create_session,
            user_id=args.user_id,
        )
    )


if __name__ == "__main__":
    sys.exit(main())

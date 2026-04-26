"""Second round-trip — exercises AgentOSRuntime (the V2 wrapper) live.

Confirms the corrected Task 12 wrapper deploys a session, runs a decision
through the real AgentOS, and tears the session down cleanly — all
against the locally-running ``scripts.agentos_dry_run.app``.

Usage (with app.py running on localhost:7777):
    OPENROUTER_API_KEY=... python -m scripts.agentos_dry_run.wrapper_probe
"""

from __future__ import annotations

import asyncio
import json
import sys

from src.runtime.agentos import AgentOSRuntime, AgentOSRuntimeError
from src.runtime.base import InstanceSpec


async def main() -> int:
    rt = AgentOSRuntime(
        api_url="http://localhost:7777",
        auth_token="",
        canonical_agent_id="dry-run-agent",
        use_output_schema=False,   # mirrors V2 default; live gate shows
                                   # OpenRouter/OpenAI rejects json-schema
    )

    print("== deploy ==")
    handle = await rt.deploy(
        InstanceSpec(
            template_key="dry_run_template",
            template_version="1",
            effective_config={"max_slippage_bps": 50, "demo": True},
            instance_owner_ref="wrapper-probe-user",
        )
    )
    print(f"handle.instance_id = {handle.instance_id!r}")
    print(f"handle.extra       = {json.dumps(handle.extra, default=str)}")

    print("\n== invoke_decide ==")
    # Fake ChallengeState-shaped object — the wrapper only needs .__dict__.
    # All required swaps already completed — FINISH is the correct answer
    # per the AgentAction contract (EXECUTE_SWAP | WAIT | FINISH).
    class _State:
        portfolio = {"So11111111111111111111111111111111111111112": 1_000_000_000}
        completed_swaps = ["sol_to_devusdc"]
        required_swaps = ["sol_to_devusdc"]
        iterations_used = 1
        elapsed_secs = 1.0
        iteration_budget = 10
        time_budget_secs = 60
        status = "finished"

    try:
        action = await rt.invoke_decide(handle, _State())
        print(f"action.type   = {action.type.value}")
        print(f"action.params = {action.params}")
    except AgentOSRuntimeError as e:
        print(f"invoke_decide raised AgentOSRuntimeError: {e}")
        # Surface the error but still teardown and exit non-zero so the
        # gate fails loudly in CI / logs.
        try:
            await rt.teardown(handle)
        except Exception:  # pragma: no cover
            pass
        return 2

    print("\n== teardown ==")
    await rt.teardown(handle)
    print("teardown complete")

    print("\n== teardown (idempotent retry) ==")
    await rt.teardown(handle)
    print("second teardown complete (no exception)")

    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

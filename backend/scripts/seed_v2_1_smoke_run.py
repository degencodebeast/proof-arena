"""Seed one completed V2.1 Cat/Verifier smoke run.

This is a local/live-smoke utility, not a benchmark runner. It inserts the
minimum Postgres rows needed for:

    GET /api/v1/cats/wallet_safety/{run_id}
    GET /api/v1/verifier/runs/{run_id}

No Solana RPC, Privy, AgentOS, wallet, or LLM path is invoked.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import (
    ACTION_SCHEMA_VERSION,
    APP_VERSION,
    CHALLENGE_VERSION,
    EVIDENCE_SCHEMA_VERSION,
)
from src.db.engine import async_session_factory
from src.db.models import (
    Agent,
    AgentInstance,
    AgentTemplate,
    Challenge,
    Run,
    RunEvent,
    VerificationArtifact,
)


_TEMPLATE_KEY = "v2_1_smoke_template"
_TEMPLATE_VERSION = "v2_1_smoke_v1"


@dataclass(frozen=True)
class SmokeRunSeedResult:
    run_id: int
    instance_id: int
    agent_id: int
    challenge_id: int
    template_id: int


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _get_or_create_template(db: AsyncSession) -> AgentTemplate:
    existing = (
        await db.execute(
            select(AgentTemplate).where(AgentTemplate.template_key == _TEMPLATE_KEY)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    template = AgentTemplate(
        template_key=_TEMPLATE_KEY,
        template_version=_TEMPLATE_VERSION,
        description="Local V2.1 smoke template for Cat and Verifier endpoint curls.",
        allowed_fields_json=json.dumps(
            [
                "max_slippage_bps",
                "token_universe",
                "max_position_size_usdc",
                "max_runtime_seconds",
                "max_iterations",
            ]
        ),
        default_config_json=json.dumps(
            {
                "max_slippage_bps": 50,
                "token_universe": ["SOL", "USDC"],
                "max_position_size_usdc": 10,
                "max_runtime_seconds": 60,
                "max_iterations": 2,
            }
        ),
        system_prompt="Local smoke template. Do not use for benchmark scoring.",
        is_deployable=1,
    )
    db.add(template)
    await db.flush()
    return template


async def seed_v2_1_smoke_run(db: AsyncSession) -> SmokeRunSeedResult:
    """Insert one completed hosted-instance run for local endpoint smoke.

    The row shape intentionally uses the public canonical-template trust label
    so both smoke curls can be anonymous 200s.
    """
    now = datetime.now(timezone.utc)
    token = _sha256(now.isoformat())
    template = await _get_or_create_template(db)

    instance = AgentInstance(
        template_id=template.template_id,
        template_version_at_deploy=template.template_version,
        instance_owner_ref=f"smoke-owner-{token[:12]}",
        effective_config_json=template.default_config_json,
        runtime_handle_json=json.dumps({"smoke": True, "token": token[:12]}),
        wallet_address=f"smoke-wallet-{token[:24]}",
        hosted_wallet_ref=f"smoke-hosted-wallet-{token[:12]}",
        wallet_provider="smoke",
        trust_label="benchmarked_canonical_template",
        status="live",
    )
    db.add(instance)
    await db.flush()

    agent = Agent(
        privy_user_id=f"instance:{instance.instance_id}",
        owner_wallet="smoke-owner-wallet",
        display_name=f"V2.1 Smoke Agent {instance.instance_id}",
        submission_type="hosted_instance",
        submission_hash=_sha256(f"smoke-agent-{instance.instance_id}"),
        system_prompt="Local smoke bridge agent.",
        config_json="{}",
        metadata_ref=f"agent_instances/{instance.instance_id}",
        provider_type="hosted_instance",
        subject_type="canonical_template",
    )
    db.add(agent)
    await db.flush()

    challenge = Challenge(
        challenge_type="swap_execution",
        challenge_version=CHALLENGE_VERSION,
        llm_provider="none",
        llm_model="none",
        config_json=json.dumps(
            {
                "smoke": True,
                "starting_usdc": 100_000_000,
                "iteration_budget": 2,
                "time_budget_secs": 60,
            }
        ),
        status="completed",
        num_contestants=1,
        num_finalized=1,
        winner_agent_id=agent.agent_id,
        started_at=now,
        ended_at=now,
    )
    db.add(challenge)
    await db.flush()

    run = Run(
        challenge_id=challenge.challenge_id,
        agent_id=agent.agent_id,
        provider_type="hosted_instance",
        status="completed",
        completion_status="complete",
        invalid_reason=None,
        starting_value=100_000_000,
        ending_value=101_000_000,
        iterations_used=2,
        run_log_hash=_sha256(f"smoke-run-log-{token}"),
        app_version=APP_VERSION,
        challenge_type="swap_execution",
        challenge_version=CHALLENGE_VERSION,
        action_schema_version=ACTION_SCHEMA_VERSION,
        evidence_schema_version=EVIDENCE_SCHEMA_VERSION,
        started_at=now,
        ended_at=now,
    )
    db.add(run)
    await db.flush()

    db.add_all(
        [
            RunEvent(
                run_id=run.run_id,
                sequence_no=1,
                event_type="observe",
                timestamp=now,
                state_snapshot_json=json.dumps({"smoke": True}),
            ),
            RunEvent(
                run_id=run.run_id,
                sequence_no=2,
                event_type="finalize",
                timestamp=now,
                result_payload_json=json.dumps({"completion_status": "complete"}),
            ),
            VerificationArtifact(
                run_id=run.run_id,
                artifact_type="smoke_metadata",
                uri_or_ref=f"local-smoke://{run.run_id}",
                content_hash=_sha256(f"smoke-artifact-{run.run_id}-{token}"),
            ),
        ]
    )
    await db.commit()

    return SmokeRunSeedResult(
        run_id=run.run_id,
        instance_id=instance.instance_id,
        agent_id=agent.agent_id,
        challenge_id=challenge.challenge_id,
        template_id=template.template_id,
    )


async def _main_async() -> int:
    async with async_session_factory() as db:
        seeded = await seed_v2_1_smoke_run(db)
    print(json.dumps(asdict(seeded), sort_keys=True))
    print(
        "curl -s http://localhost:8000/api/v1/cats/wallet_safety/"
        f"{seeded.run_id} | jq ."
    )
    print(
        "curl -s http://localhost:8000/api/v1/verifier/runs/"
        f"{seeded.run_id} | jq ."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args()
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())

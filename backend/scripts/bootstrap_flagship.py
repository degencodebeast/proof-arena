"""bootstrap_flagship.py — one-shot CLI for Task 5 / plan A-3.

Reserves the canonical flagship ``Agent`` row for a template and links
``AgentTemplate.benchmark_subject_agent_id``. Idempotent: safe to run
multiple times — the second run short-circuits via the template FK.

Usage::

    python scripts/bootstrap_flagship.py
    python scripts/bootstrap_flagship.py --template-key swap_executor_v1
    python scripts/bootstrap_flagship.py --dry-run

``--dry-run`` is a read-only probe. It does NOT call the mutating
bootstrap path; it inspects the current template + flagship state
through ``FlagshipService.get_flagship_agent(...)`` and prints the
action it would take if run without the flag. Safe to run in any
environment — it cannot create, update, or delete rows.

Out of scope here (Task 18): deploying a hosted flagship
``AgentInstance`` or assigning
``agent_instances.trust_label = "benchmarked_canonical_template"``.
Those belong to Task 18 / plan D-1.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import async_session_factory
from src.db.models import AgentTemplate
from src.services.flagship_service import FlagshipService, FlagshipServiceError


async def _bootstrap_once(
    session: AsyncSession, template_key: str, dry_run: bool
) -> int:
    """Run one bootstrap attempt against the given session.

    Extracted for tests: dependency-inject an ``AsyncSession`` so in-memory
    SQLite tests can drive the CLI without touching production engine wiring.

    Returns process exit code (0 on success, 1 on error).
    """
    svc = FlagshipService(session)

    if dry_run:
        # Read-only probe. Never calls the mutating path.
        tmpl = (
            await session.execute(
                select(AgentTemplate).where(
                    AgentTemplate.template_key == template_key
                )
            )
        ).scalar_one_or_none()
        if tmpl is None:
            print(
                f"bootstrap_flagship: template {template_key!r} not found",
                file=sys.stderr,
            )
            return 1

        existing = await svc.get_flagship_agent(template_key)
        if existing is not None:
            print(
                f"[dry-run] flagship already exists: "
                f"agent_id={existing.agent_id} "
                f"display_name={existing.display_name!r} "
                f"template_fk={tmpl.benchmark_subject_agent_id}"
            )
        else:
            print(
                f"[dry-run] would bootstrap flagship for "
                f"template={template_key!r} (agent does not exist yet)"
            )
        return 0

    # Mutating path.
    try:
        agent = await svc.ensure_flagship_exists(template_key)
    except FlagshipServiceError as exc:
        print(f"bootstrap_flagship: {exc}", file=sys.stderr)
        return 1

    tmpl = (
        await session.execute(
            select(AgentTemplate).where(
                AgentTemplate.template_key == template_key
            )
        )
    ).scalar_one()
    print(
        f"flagship agent_id={agent.agent_id} "
        f"display_name={agent.display_name!r} "
        f"template.benchmark_subject_agent_id={tmpl.benchmark_subject_agent_id}"
    )
    return 0


async def _main_async(template_key: str, dry_run: bool) -> int:
    async with async_session_factory() as session:
        return await _bootstrap_once(session, template_key, dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--template-key", default="swap_executor_v1")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Read-only probe. Inspects the current template + flagship "
            "state and prints the intended action without calling the "
            "mutating bootstrap path."
        ),
    )
    args = parser.parse_args()
    return asyncio.run(_main_async(args.template_key, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())

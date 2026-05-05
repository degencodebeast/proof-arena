"""FastAPI app builder for the AgentOS service.

Returns the AgentOS-built FastAPI app with the canonical V2 agent
declared at process startup. Uvicorn drives the lifecycle.
"""

from __future__ import annotations

from typing import Any

from agno.agent import Agent
from agno.os import AgentOS
from fastapi import FastAPI

from agentos_app.agent import (
    build_canonical_rebalance_executor_agent,
    build_canonical_swap_executor_agent,
)
from agentos_app.config import AgentOSAppSettings, load_settings


def build_agentos(
    settings: AgentOSAppSettings | None = None,
) -> AgentOS:
    """Construct the ``AgentOS`` instance with both canonical agents pre-registered.

    Spec §5.3: V2.1 hosted runtime pre-registers both ``swap_executor_v1`` and
    ``rebalance_executor_v1`` canonical agents. Both decision-only (``tools=[]``);
    Proof Arena's backend owns validation, execution, evidence, and scoring.
    """
    settings = settings or load_settings()
    db = _build_db(settings)
    swap_canonical: Agent = build_canonical_swap_executor_agent(settings, db=db)
    rebalance_canonical: Agent = build_canonical_rebalance_executor_agent(settings, db=db)
    return AgentOS(
        id="proof-arena-agentos",
        name="Proof Arena AgentOS",
        description=(
            "Proof Arena V2.1 hosted runtime. Pre-registers the canonical "
            "swap_executor_v1 and rebalance_executor_v1 agents. Decision-only — "
            "Proof Arena's backend owns validation, execution, evidence, and scoring."
        ),
        db=db,
        agents=[swap_canonical, rebalance_canonical],
        # Telemetry off by default for a self-hosted private deployment.
        telemetry=False,
    )


def build_agentos_app(
    settings: AgentOSAppSettings | None = None,
) -> FastAPI:
    """Return the ASGI app uvicorn binds to."""
    return build_agentos(settings).get_app()


def _build_db(settings: AgentOSAppSettings) -> Any | None:
    """Build Agno's DB adapter when live session persistence is configured.

    Agno creates the session table automatically if it does not exist.
    Empty URL keeps local/tests DB-free, but live Coolify deploys should
    set AGENTOS_DATABASE_URL so /sessions works.
    """
    if not settings.database_url:
        return None

    from agno.db.postgres import PostgresDb

    return PostgresDb(
        db_url=settings.database_url,
        session_table="proof_arena_agentos_sessions",
        id="proof-arena-agentos-db",
    )

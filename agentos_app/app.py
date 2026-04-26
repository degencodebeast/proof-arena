"""FastAPI app builder for the AgentOS service.

Returns the AgentOS-built FastAPI app with the canonical V2 agent
declared at process startup. Uvicorn drives the lifecycle.
"""

from __future__ import annotations

from agno.agent import Agent
from agno.os import AgentOS
from fastapi import FastAPI

from agentos_app.agent import build_canonical_swap_executor_agent
from agentos_app.config import AgentOSAppSettings, load_settings


def build_agentos(
    settings: AgentOSAppSettings | None = None,
) -> AgentOS:
    """Construct the ``AgentOS`` instance with exactly one agent."""
    settings = settings or load_settings()
    canonical: Agent = build_canonical_swap_executor_agent(settings)
    return AgentOS(
        id="proof-arena-agentos",
        name="Proof Arena AgentOS",
        description=(
            "Proof Arena V2 hosted runtime. Pre-registers the canonical "
            "swap_executor_v1 agent. Decision-only — Proof Arena's "
            "backend owns validation, execution, evidence, and scoring."
        ),
        agents=[canonical],
        # Telemetry off by default for a self-hosted private deployment.
        telemetry=False,
    )


def build_agentos_app(
    settings: AgentOSAppSettings | None = None,
) -> FastAPI:
    """Return the ASGI app uvicorn binds to."""
    return build_agentos(settings).get_app()

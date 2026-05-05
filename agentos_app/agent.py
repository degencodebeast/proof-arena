"""Canonical V2 agent factories.

Decision-only contract (Task 12 contract note §3): agents do not own
wallets, call Orca, or execute swaps. ``tools=[]`` is therefore a hard
invariant on ALL canonical agents.

Mirrors the provider switch in ``backend/src/agents/arena_agent.py``
so model selection stays consistent across V1 LocalAgentProvider and
V2 hosted runtime.
"""

from __future__ import annotations

from typing import Any

from agno.agent import Agent

from agentos_app.canonical_template_contract import (
    REBALANCE_EXECUTOR_V1_SEED,
    canonical_system_prompt,
)
from agentos_app.config import AgentOSAppSettings, load_settings


SUPPORTED_PROVIDERS = ("openrouter", "anthropic", "openai", "google")


def _build_canonical_agent(
    *,
    agent_id: str,
    instructions: str,
    settings: AgentOSAppSettings,
    db: Any | None,
) -> Agent:
    """Shared factory for canonical agents.

    Both canonical agents (swap, rebalance) MUST have ``tools=[]`` per the
    V0 decision-only invariant (spec §5.3, §7.2). Generalized tool calling
    is a follow-on runtime spec.
    """
    return Agent(
        id=agent_id,
        name=agent_id,
        instructions=instructions,
        model=_create_model(settings),
        db=db,
        tools=[],         # decision-only invariant — DO NOT CHANGE
        markdown=False,
    )


def build_canonical_swap_executor_agent(
    settings: AgentOSAppSettings | None = None,
    db: Any | None = None,
) -> Agent:
    """Return the pre-registered V2 canonical agent.

    The returned ``Agent`` has:
    - ``id`` = the env-pair-bound ``canonical_agent_id`` (default
      ``"swap_executor_v1"``).
    - ``instructions`` = ``SWAP_EXECUTOR_V1_SEED["system_prompt"]``
      verbatim (read at call time, not cached, so a backend-side seed
      edit picked up at process restart).
    - ``tools=[]`` — decision-only.
    - ``markdown=False`` — plain JSON-friendly output.
    - deterministic temp via the model factory.
    """
    settings = settings or load_settings()
    return _build_canonical_agent(
        agent_id=settings.canonical_agent_id,
        instructions=canonical_system_prompt(),
        settings=settings,
        db=db,
    )


def build_canonical_rebalance_executor_agent(
    settings: AgentOSAppSettings | None = None,
    db: Any | None = None,
) -> Agent:
    """V0 rebalance canonical agent — decision-only.

    Keeps tools=[] and reads system_prompt verbatim from
    REBALANCE_EXECUTOR_V1_SEED (object identity preserved). Generalized
    tool calling is a follow-on runtime spec; do not add tools here.

    Per V0 spec §5.3: agent emits existing AgentAction shapes only
    (preferably FINISH); RebalanceExecutionChallenge does the
    deterministic plan + evidence work in Task 13+.
    """
    settings = settings or load_settings()
    return _build_canonical_agent(
        agent_id=REBALANCE_EXECUTOR_V1_SEED["template_key"],
        instructions=REBALANCE_EXECUTOR_V1_SEED["system_prompt"],
        settings=settings,
        db=db,
    )


def _create_model(settings: AgentOSAppSettings):
    """Resolve the model class for the configured provider.

    Temperature pinned to 0 for benchmark reproducibility — same rule
    as ``backend/src/agents/arena_agent.py``.
    """
    provider = settings.llm_provider
    model_id = settings.llm_model

    if provider == "openrouter":
        from agno.models.openrouter import OpenRouter

        # Agno's OpenRouter reads ``OPENROUTER_API_KEY`` from env by
        # default; if the operator wired it via pydantic-settings only,
        # surface it back through env so the SDK picks it up.
        if settings.openrouter_api_key:
            import os

            os.environ.setdefault(
                "OPENROUTER_API_KEY", settings.openrouter_api_key
            )
        return OpenRouter(id=model_id, temperature=0)

    if provider == "anthropic":
        from agno.models.anthropic import Claude

        return Claude(id=model_id, temperature=0)

    if provider == "openai":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(id=model_id, temperature=0)

    if provider == "google":
        from agno.models.google import Gemini

        return Gemini(id=model_id, temperature=0)

    raise ValueError(
        f"Unsupported LLM provider: {provider!r}. "
        f"V2 supports: {', '.join(SUPPORTED_PROVIDERS)}."
    )

"""Canonical V2 agent factory.

Decision-only contract (Task 12 contract note §3): the agent does not
own wallets, call Orca, or execute swaps. ``tools=[]`` is therefore a
hard invariant.

Mirrors the provider switch in ``backend/src/agents/arena_agent.py``
so model selection stays consistent across V1 LocalAgentProvider and
V2 hosted runtime.
"""

from __future__ import annotations

from agno.agent import Agent

from agentos_app.canonical_template_contract import (
    canonical_system_prompt,
)
from agentos_app.config import AgentOSAppSettings, load_settings


SUPPORTED_PROVIDERS = ("openrouter", "anthropic", "openai", "google")


def build_canonical_swap_executor_agent(
    settings: AgentOSAppSettings | None = None,
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
    return Agent(
        id=settings.canonical_agent_id,
        name=settings.canonical_agent_id,
        instructions=canonical_system_prompt(),
        model=_create_model(settings),
        tools=[],
        markdown=False,
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

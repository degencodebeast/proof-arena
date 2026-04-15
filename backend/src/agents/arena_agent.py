"""Arena Agent — Agno Agent factory for benchmark execution.

V1 Agno boundary:
- Agent decides actions only (EXECUTE_SWAP, WAIT, FINISH)
- No memory, knowledge, teams, learning, or DB
- Temperature = 0 for reproducibility
- Stateless: no hidden state across decisions
- Tools are stateless closures, not global instances

Supported providers: anthropic, openai, google, openrouter.
OpenRouter: uses explicit model ID, no auto-routing/fallback models.
Requires OPENROUTER_API_KEY env var.
"""

from __future__ import annotations

from agno.agent import Agent

SUPPORTED_PROVIDERS = ("anthropic", "openai", "google", "openrouter")


def create_arena_agent(
    system_prompt: str,
    llm_provider: str,
    llm_model: str,
    tools: list,
) -> Agent:
    """Create an Agno Agent for benchmark execution.

    Args:
        system_prompt: The strategy's system prompt from submission.
        llm_provider: LLM provider name (anthropic, openai, google, openrouter).
        llm_model: Model ID (e.g., claude-sonnet-4-20250514, openai/gpt-4o).
        tools: List of Agno tool functions.

    Returns:
        Configured Agno Agent with deterministic settings.
    """
    model = _create_model(llm_provider, llm_model)

    return Agent(
        model=model,
        instructions=system_prompt,
        tools=tools,
        markdown=False,
    )


def _create_model(llm_provider: str, llm_model: str):
    """Create the appropriate Agno model based on provider.

    Temperature = 0 for benchmark reproducibility.
    OpenRouter: explicit model ID only, no fallback `models` list.
    """
    if llm_provider == "anthropic":
        from agno.models.anthropic import Claude

        return Claude(id=llm_model, temperature=0)

    elif llm_provider == "openai":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(id=llm_model, temperature=0)

    elif llm_provider == "google":
        from agno.models.google import Gemini

        return Gemini(id=llm_model, temperature=0)

    elif llm_provider == "openrouter":
        from agno.models.openrouter import OpenRouter

        # Explicit model ID, no auto-routing/fallback models.
        # Temperature passed via OpenAI-compatible params.
        return OpenRouter(id=llm_model, temperature=0)

    else:
        raise ValueError(
            f"Unsupported LLM provider: '{llm_provider}'. "
            f"V1 supports: {', '.join(SUPPORTED_PROVIDERS)}."
        )

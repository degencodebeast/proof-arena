"""Typed env-var settings for the AgentOS service.

Mirrors the pattern in ``backend/src/config.py`` (pydantic-settings
``BaseSettings``). Each field is bound to its DOCUMENTED env-var name
via ``Field(validation_alias=...)`` — bare field names are not enough
because pydantic-settings would otherwise read e.g.
``CANONICAL_AGENT_ID`` instead of the ``AGENTOS_CANONICAL_AGENT_ID``
documented in ``v2_infra.md`` and ``task29-edge-case-spec.md`` §10.

Vendor API keys (``OPENROUTER_API_KEY``, ``ANTHROPIC_API_KEY``, etc.)
deliberately do NOT carry the ``AGENTOS_`` prefix: the underlying agno
SDK reads them with their canonical names + the V1 backend env shares
them, so double-prefixing would force operators to configure each key
twice.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentOSAppSettings(BaseSettings):
    """Runtime config for the AgentOS service.

    All defaults are devnet/private-network-safe. Operators override
    via env when deploying to Coolify.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # No `env_prefix` — vendor API keys (OPENROUTER_API_KEY etc.)
        # need their canonical SDK names, which differ from the
        # AGENTOS_-prefixed names of the operational fields. Each
        # field below specifies its alias explicitly.
        populate_by_name=True,
    )

    # ----- AgentOS-side bindings --------------------------------------
    # The default MUST match `backend.AGENTOS_CANONICAL_AGENT_ID`'s
    # default + the backend Task 12 contract. Drift = `create_session`
    # 404 from the backend side.
    canonical_agent_id: str = Field(
        default="swap_executor_v1",
        validation_alias="AGENTOS_CANONICAL_AGENT_ID",
    )

    # ----- Server bind --------------------------------------------------
    # Surfaced through the Dockerfile's shell-form CMD, which
    # interpolates ${AGENTOS_HOST:-0.0.0.0} and ${AGENTOS_PORT:-7000}.
    # Reading them in settings is for parity / smoke-checks; the actual
    # uvicorn bind happens at the container CMD layer.
    host: str = Field(default="0.0.0.0", validation_alias="AGENTOS_HOST")
    port: int = Field(default=7000, validation_alias="AGENTOS_PORT")

    # ----- Session storage ---------------------------------------------
    # Agno's /sessions API needs a database-backed session store for the
    # live AgentOS deployment. Backend DATABASE_URL uses asyncpg; this
    # AgentOS URL should use psycopg, e.g.
    # postgresql+psycopg://user:pass@postgres:5432/proof_arena.
    database_url: str = Field(default="", validation_alias="AGENTOS_DATABASE_URL")

    # ----- Model selection ---------------------------------------------
    # OpenRouter is the Phase-0 LIVE-GATE-validated combo (see
    # `task12-agentos-contract-note.md` §1 LIVE GATE). Operator may
    # swap to `anthropic` / `openai` / `google` post-V2; the agent
    # factory uses the same provider switch as the V1 LocalAgentProvider.
    llm_provider: str = Field(
        default="openrouter",
        validation_alias="AGENTOS_LLM_PROVIDER",
    )
    llm_model: str = Field(
        default="openai/gpt-4o-mini",
        validation_alias="AGENTOS_LLM_MODEL",
    )

    # ----- Vendor secrets ----------------------------------------------
    # Empty default fails loudly when the agent first runs — better
    # than silently using a wrong key. Env names are SDK-canonical, NOT
    # AGENTOS_-prefixed, so V1 backend env stays compatible.
    openrouter_api_key: str = Field(
        default="", validation_alias="OPENROUTER_API_KEY"
    )
    anthropic_api_key: str = Field(
        default="", validation_alias="ANTHROPIC_API_KEY"
    )
    openai_api_key: str = Field(
        default="", validation_alias="OPENAI_API_KEY"
    )
    google_api_key: str = Field(
        default="", validation_alias="GOOGLE_API_KEY"
    )


def load_settings() -> AgentOSAppSettings:
    """Factory — keeps tests substitutable via dependency injection."""
    return AgentOSAppSettings()

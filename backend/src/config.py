"""Application configuration — pydantic-settings with version constants.

Version constants per VERSIONING.md initial defaults.
All benchmark-semantic versions are independent from app_version.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Version constants (per VERSIONING.md)
# ---------------------------------------------------------------------------

APP_VERSION = "0.1.0"
API_VERSION = "v1"
CHALLENGE_VERSION = "swap_execution_v1"
RANK_VERSION = "rank_v1"
EVIDENCE_SCHEMA_VERSION = "evidence_v1"
ACTION_SCHEMA_VERSION = "agent_action_v1"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = (
        "postgresql+asyncpg://arena:arena@localhost:5432/agent_arena"
    )

    # Solana
    SOLANA_RPC_URL: str = "https://api.devnet.solana.com"
    SOLANA_CLUSTER: str = "devnet"  # devnet | mainnet-beta | testnet
    PROGRAM_ID: str = ""
    AUTHORITY_KEYPAIR_PATH: str = ""
    TREASURY_KEYPAIR_PATH: str = ""
    USDC_MINT: str = ""  # Cluster-specific USDC mint address

    # Privy
    PRIVY_APP_ID: str = ""
    PRIVY_APP_SECRET: str = ""
    # V2 Task 8 — authorization private key for the Privy agentic-wallet
    # posture. Format: PEM-encoded PKCS8 P-256 (SECP256R1). Single-line
    # .env values may use literal `\n` escapes — the privy_signing service
    # normalizes them on load. No other key formats are accepted.
    PRIVY_AUTHORIZATION_PRIVATE_KEY: str = ""

    # V2 Task 12 — AgentOS hosted-runtime configuration.
    # V2 uses ONE self-hosted AgentOS FastAPI process as the runtime substrate
    # (see V2 plan §2 and .taskmaster/docs/task12-agentos-contract-note.md).
    # Canonical agents (e.g. swap_executor_v1) are pre-registered at AgentOS
    # process startup; per-instance runtime isolation is session-based.
    AGENTOS_API_URL: str = ""          # base_url of the self-hosted AgentOS FastAPI process
    AGENTOS_AUTH_TOKEN: str = ""       # optional JWT; empty = unauthed (valid on private net)
    # V2 Task 38: Phase-0 V0-VAL-3 locked default; override only for staging/test profiles.
    AGENTOS_CANONICAL_AGENT_ID: str = "swap_executor_v1"  # pre-registered agent id for swap_executor_v1

    # V2 Task 23 — hosted-wallet deploy stack configuration. These two
    # settings are required by InstanceService.__init__ (Task 13) and
    # read by src/api/instances.py::get_instance_service() (Task 23).
    # If either is empty, POST /api/v1/instances/deploy returns 503
    # (deploy stack not configured) — the same shape as Task 14's
    # get_runtime() factory.
    HOSTED_WALLET_POLICY_ID: str = ""  # pre-existing Privy policy id (Task 9, Phase-0 locked)
    AUTHORIZATION_PUBKEY_B64: str = ""  # base64-DER P-256 SPKI of the Proof Arena authorization key (Task 8)

    # V2 Task 10 — optional override path for the wallet-policy allowlist
    # profile JSON file. Empty (default) → use the Phase-0-locked
    # ORCA_DEVNET_ALLOWLIST from src.policy.allowlists. Set this only for
    # test substitution or a future non-default profile.
    ALLOWLIST_PROFILE_PATH: str = ""

    # V2 Task 11 — Orca Whirlpools devnet hosted-swap configuration.
    # Evidence: PHASE_0_CLOSEOUT_NOTE.md V0-VAL-3.
    # V2 Task 38: Phase-0 V0-VAL-3 locked defaults; override only for staging/test profiles.
    V2_HOSTED_SWAP_POOL: str = "3KBZiL2g8C7tiJ32hTv5v3KM7aK9htpqTw4cTXz1HvPt"  # SOL/devUSDC Whirlpool
    V2_HOSTED_USDC_MINT: str = "BRjpCHtyQLNCo8gqRUr8jtdAj5AjPYQaoqbvcZiHok1k"  # Orca devUSDC mint
    ORCA_SWAP_SCRIPT_PATH: str = "scripts/orca_swap.js"

    # OpenRouter (optional — for openrouter LLM provider)
    OPENROUTER_API_KEY: str = ""

    # Jupiter — verify current URL via Context7 before integration
    JUPITER_API_URL: str = "https://api.jup.ag"

    # App identity
    APP_VERSION: str = APP_VERSION
    API_VERSION: str = API_VERSION
    CHALLENGE_VERSION: str = CHALLENGE_VERSION
    RANK_VERSION: str = RANK_VERSION
    EVIDENCE_SCHEMA_VERSION: str = EVIDENCE_SCHEMA_VERSION
    ACTION_SCHEMA_VERSION: str = ACTION_SCHEMA_VERSION

    # Limits
    MAX_SUBMISSIONS_PER_USER: int = 3
    SUBMISSION_COOLDOWN_SECS: int = 300
    QUOTE_MAX_AGE_SECS: int = 30

    # Admin
    ADMIN_API_KEY: str = ""  # Required for admin endpoints

    # Browser CORS. Empty/default keeps the API same-origin/private by
    # default; live/local frontend origins must be explicitly configured.
    CORS_ORIGINS: str = ""

    # Debug
    DEBUG: bool = False

    @property
    def cors_origins(self) -> list[str]:
        """Coolify-friendly comma-separated browser origins."""
        if not self.CORS_ORIGINS:
            return []
        return [
            origin.strip().rstrip("/")
            for origin in self.CORS_ORIGINS.split(",")
            if origin.strip()
        ]


settings = Settings()

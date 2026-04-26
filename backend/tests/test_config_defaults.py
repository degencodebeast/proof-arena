"""Task 38 — V2 Runtime Config Defaults + Secret Boundary.

Covers ``.taskmaster/docs/task38-config-defaults-spec.md`` T1-T5:
- Phase-0 V0-VAL-3 locked defaults for the three "stable + non-secret +
  frequently retyped" V2 settings.
- Env override precedence (the pydantic-settings ``env > defaults`` rule
  verified 2026-04-26 via Context7).
- ``AUTHORIZATION_PUBKEY_B64`` MUST stay ``""`` — regression guard against
  a future PR that defaults it to a leaked test value. The pubkey must
  match ``PRIVY_AUTHORIZATION_PRIVATE_KEY`` per-environment; defaulting
  it would silently break every Privy authorization-signature.
- ``HOSTED_WALLET_POLICY_ID`` MUST stay ``""`` — Privy policy id is
  created out-of-band per-environment.

Tests construct fresh ``Settings(_env_file=None)`` instances so .env file
content on the developer machine does not leak into results. ``monkeypatch``
provides isolated env mutation; pytest restores on teardown.
"""

from __future__ import annotations

import os


# Required for src.config import without leaking real DB / Privy values.
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-t38")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/unused",
)


PHASE0_AGENT_ID = "swap_executor_v1"
PHASE0_USDC_MINT = "BRjpCHtyQLNCo8gqRUr8jtdAj5AjPYQaoqbvcZiHok1k"
PHASE0_SWAP_POOL = "3KBZiL2g8C7tiJ32hTv5v3KM7aK9htpqTw4cTXz1HvPt"


def _fresh_settings():
    """Construct a Settings instance that ignores any developer .env file.

    `_env_file=None` is the documented opt-out per pydantic-settings docs
    (https://docs.pydantic.dev/latest/concepts/pydantic_settings/, verified
    via Context7 2026-04-26). os.environ values still apply, which is what
    the env-override tests rely on.
    """
    from src.config import Settings

    return Settings(_env_file=None)


# ======================================================================
# T1 — defaults are the Phase-0 V0-VAL-3 locked strings
# ======================================================================


def test_t1_phase0_defaults_present(monkeypatch):
    """Without any env override, the three vars carry their Phase-0 defaults.

    monkeypatch.delenv tolerates the var being absent (raising=False) so the
    test is robust to whatever the developer-machine env happens to look like.
    """
    monkeypatch.delenv("AGENTOS_CANONICAL_AGENT_ID", raising=False)
    monkeypatch.delenv("V2_HOSTED_USDC_MINT", raising=False)
    monkeypatch.delenv("V2_HOSTED_SWAP_POOL", raising=False)

    s = _fresh_settings()
    assert s.AGENTOS_CANONICAL_AGENT_ID == PHASE0_AGENT_ID
    assert s.V2_HOSTED_USDC_MINT == PHASE0_USDC_MINT
    assert s.V2_HOSTED_SWAP_POOL == PHASE0_SWAP_POOL


# ======================================================================
# T2 — env override wins for AGENTOS_CANONICAL_AGENT_ID
# ======================================================================


def test_t2_env_override_wins_for_agentos_canonical_agent_id(monkeypatch):
    """Operator-supplied env value MUST override the code default. This
    keeps the staging/test-profile escape hatch live."""
    monkeypatch.setenv("AGENTOS_CANONICAL_AGENT_ID", "custom_agent_t38")
    s = _fresh_settings()
    assert s.AGENTOS_CANONICAL_AGENT_ID == "custom_agent_t38"


# ======================================================================
# T3 — AUTHORIZATION_PUBKEY_B64 default stays "" (regression guard)
# ======================================================================


def test_t3_authorization_pubkey_b64_default_stays_empty(monkeypatch):
    """`AUTHORIZATION_PUBKEY_B64` is non-secret config that MUST match
    `PRIVY_AUTHORIZATION_PRIVATE_KEY` per-environment. Defaulting it would
    silently mis-bind every Privy authorization-signature (Task 39 contract).
    Fail-loud with `""` is the correct posture; this test guards against a
    future PR that defaults it to a leaked test value.
    """
    monkeypatch.delenv("AUTHORIZATION_PUBKEY_B64", raising=False)
    s = _fresh_settings()
    assert s.AUTHORIZATION_PUBKEY_B64 == ""


# ======================================================================
# T4 — env override wins for V2_HOSTED_USDC_MINT + V2_HOSTED_SWAP_POOL
# ======================================================================


def test_t4_env_override_wins_for_orca_vars(monkeypatch):
    """Staging profiles can swap mint and pool via env."""
    monkeypatch.setenv("V2_HOSTED_USDC_MINT", "test_mint_t38")
    monkeypatch.setenv("V2_HOSTED_SWAP_POOL", "test_pool_t38")
    s = _fresh_settings()
    assert s.V2_HOSTED_USDC_MINT == "test_mint_t38"
    assert s.V2_HOSTED_SWAP_POOL == "test_pool_t38"


# ======================================================================
# T5 — HOSTED_WALLET_POLICY_ID default stays "" (regression guard)
# ======================================================================


def test_t5_hosted_wallet_policy_id_default_stays_empty(monkeypatch):
    """The Privy policy id is created out-of-band per-environment.
    Hardcoding any value would bind Coolify deploys to a specific Privy
    account's policy that may not exist or carry the wrong allowlist.
    """
    monkeypatch.delenv("HOSTED_WALLET_POLICY_ID", raising=False)
    s = _fresh_settings()
    assert s.HOSTED_WALLET_POLICY_ID == ""

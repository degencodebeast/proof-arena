"""V2 Phase P0 RED tests — InstancePolicyEngine behavior.

Targets backend/src/policy/engine.py (not yet implemented).

Scope is deliberately narrow:
- validate_spec() enforces the V2 5-field customization envelope
- unknown fields are rejected (N2 — V2.1 scope can't leak in)
- out-of-range values are rejected
- build_wallet_policy is parameterized by an `allowlist_profile` (the actual
  provider-specific shape is derived in V0-VAL-2 and injected, not hardcoded here)
- record_consent produces a DeploymentConsent with the 4 required acknowledgments
"""

from __future__ import annotations

import os

import pytest


os.environ["ADMIN_API_KEY"] = "test-admin-key-p0"
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/unused"
)


# ---------------------------------------------------------------------------
# validate_spec — envelope enforcement
# ---------------------------------------------------------------------------


def _valid_spec() -> dict:
    return {
        "allowed_token_universe": ["So11111111111111111111111111111111111111112"],
        "max_slippage_bps": 100,
        "max_position_size": 50_000_000,
        "max_iterations": 10,
        "max_runtime_seconds": 120,
    }


def test_policy_engine_accepts_valid_five_field_envelope():
    """Happy path — every V2 locked envelope field present and in range."""
    from src.policy.engine import InstancePolicyEngine

    engine = InstancePolicyEngine()
    result = engine.validate_spec(_valid_spec())
    assert result.ok is True, f"Expected ok=True; got {result.errors}"
    assert result.errors == []


def test_policy_engine_rejects_unknown_envelope_field():
    """N2 — unknown fields mean V2.1 scope is leaking in; reject loudly."""
    from src.policy.engine import InstancePolicyEngine

    bad = _valid_spec()
    bad["enable_mev_search"] = True  # not a V2 envelope field

    engine = InstancePolicyEngine()
    result = engine.validate_spec(bad)
    assert result.ok is False
    assert any("enable_mev_search" in e or "unknown" in e.lower() for e in result.errors)


def test_policy_engine_rejects_missing_required_field():
    """All 5 envelope fields are required."""
    from src.policy.engine import InstancePolicyEngine

    bad = _valid_spec()
    del bad["max_slippage_bps"]

    engine = InstancePolicyEngine()
    result = engine.validate_spec(bad)
    assert result.ok is False
    assert any("max_slippage_bps" in e for e in result.errors)


def test_policy_engine_rejects_slippage_out_of_range():
    """max_slippage_bps must fit the locked range."""
    from src.policy.engine import InstancePolicyEngine

    too_high = _valid_spec()
    too_high["max_slippage_bps"] = 10_000  # 100% slippage is absurd

    engine = InstancePolicyEngine()
    result = engine.validate_spec(too_high)
    assert result.ok is False
    assert any("slippage" in e.lower() for e in result.errors)


def test_policy_engine_rejects_negative_position_size():
    from src.policy.engine import InstancePolicyEngine

    bad = _valid_spec()
    bad["max_position_size"] = -1

    engine = InstancePolicyEngine()
    result = engine.validate_spec(bad)
    assert result.ok is False


def test_policy_engine_rejects_empty_token_universe():
    from src.policy.engine import InstancePolicyEngine

    bad = _valid_spec()
    bad["allowed_token_universe"] = []

    engine = InstancePolicyEngine()
    result = engine.validate_spec(bad)
    assert result.ok is False


# ---------------------------------------------------------------------------
# build_wallet_policy — parameterized by V0-VAL-2 allowlist_profile
# ---------------------------------------------------------------------------


def test_build_wallet_policy_accepts_allowlist_profile():
    """Policy JSON is provider-agnostic at this layer. The shape is derived
    from V0-VAL-2 observations and injected as `allowlist_profile`.

    P0 only proves that:
    - the engine consumes an allowlist_profile parameter
    - the produced policy references the envelope's max_position_size
    - the produced policy references the chain target (devnet)
    """
    from src.policy.engine import InstancePolicyEngine

    engine = InstancePolicyEngine()
    spec = _valid_spec()
    allowlist_profile = {
        # Placeholder shape — actual program IDs come from V0-VAL-2.
        "program_allowlist": ["{{V0_VAL_2_JUPITER_V6}}"],
        "token_program_allowlist": ["{{V0_VAL_2_SPL_TOKEN}}"],
        "compute_budget_program": "{{V0_VAL_2_COMPUTE_BUDGET}}",
    }

    policy = engine.build_wallet_policy(
        spec=spec,
        allowlist_profile=allowlist_profile,
        chain="devnet",
    )
    assert isinstance(policy, dict)
    # max_position_size propagates into the policy so the enclave can enforce.
    policy_str = repr(policy)
    assert "50000000" in policy_str or str(spec["max_position_size"]) in policy_str
    # chain marker present.
    assert "devnet" in policy_str.lower()


def test_build_wallet_policy_refuses_mainnet():
    """Task 16 invariant — no V2 flow targets mainnet. Engine fails closed."""
    from src.policy.engine import InstancePolicyEngine

    engine = InstancePolicyEngine()
    with pytest.raises(Exception) as exc:
        engine.build_wallet_policy(
            spec=_valid_spec(),
            allowlist_profile={"program_allowlist": []},
            chain="mainnet-beta",
        )
    assert "devnet" in str(exc.value).lower() or "mainnet" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# record_consent — DeploymentConsent with 4 acknowledgments
# ---------------------------------------------------------------------------


def test_record_consent_requires_four_acknowledgments():
    """Per plan invariant 9: consent must carry devnet, platform-signing,
    spend caps, no-indemnity acknowledgments. Missing any → raise."""
    from src.policy.engine import InstancePolicyEngine

    engine = InstancePolicyEngine()
    missing = {
        "devnet_only_acknowledged": True,
        "platform_managed_signing_acknowledged": True,
        "spend_caps_acknowledged": True,
        # no_indemnity missing
    }
    with pytest.raises(Exception):
        engine.record_consent(missing)


def test_record_consent_returns_hashable_consent_record():
    """Consent must be hashable so its sha256 can go in a VerificationArtifact."""
    import hashlib

    from src.policy.engine import InstancePolicyEngine

    engine = InstancePolicyEngine()
    consent = {
        "devnet_only_acknowledged": True,
        "platform_managed_signing_acknowledged": True,
        "spend_caps_acknowledged": True,
        "no_indemnity_acknowledged": True,
    }
    record = engine.record_consent(consent)

    # Record has a `canonical_json` and `content_hash` (sha256 hex).
    assert hasattr(record, "canonical_json")
    assert hasattr(record, "content_hash")
    assert len(record.content_hash) == 64  # sha256 hex
    # Hash must actually be sha256 of the canonical_json.
    recomputed = hashlib.sha256(record.canonical_json.encode("utf-8")).hexdigest()
    assert record.content_hash == recomputed

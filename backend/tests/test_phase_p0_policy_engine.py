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


# ===========================================================================
# Task 10 — Wallet Policy Builder (transfer_cap + default_action + allowlist)
#
# Scope: provider-agnostic engine contract only. Privy-specific
# `{rules: [...]}` request-shape tests belong in
# backend/tests/test_task_9_hosted_wallet.py (or a future
# wallet-service policy-create test), NOT here. The engine output is
# passed through a provider translator at the wallet-service integration
# boundary; mixing that concern in here would blur the very boundary the
# V2 plan locks.
# ===========================================================================


# --- allowlist profile config (Task 10.1) --------------------------------


# Six-program Orca devnet allowlist, authoritative source:
# PHASE_0_CLOSEOUT_NOTE.md §V0-VAL-2 (derived from SOL→devUSDC swap tx
# 266Lc9oNy9fPDnSAVdUMFQfeUjWSHyiciXQSPT3Mb5PrRQQ82GKKc6NDb71WM3rSUmbSTS9hrTf4hWYAMc2AjCqU
# at devnet slot 456581764).
_PHASE_0_ORCA_DEVNET_PROGRAMS = [
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
    "11111111111111111111111111111111",
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
    "ComputeBudget111111111111111111111111111111",
]


def test_orca_devnet_allowlist_matches_phase_0_evidence():
    """The default constant must be the exact 6-program Phase 0 set."""
    from src.policy.allowlists import ORCA_DEVNET_ALLOWLIST

    assert isinstance(ORCA_DEVNET_ALLOWLIST, dict)
    assert set(ORCA_DEVNET_ALLOWLIST["programs"]) == set(
        _PHASE_0_ORCA_DEVNET_PROGRAMS
    )
    # Order-stable for golden-output tests downstream.
    assert ORCA_DEVNET_ALLOWLIST["programs"] == _PHASE_0_ORCA_DEVNET_PROGRAMS


def test_load_allowlist_profile_none_returns_default():
    from src.policy.allowlists import ORCA_DEVNET_ALLOWLIST, load_allowlist_profile

    loaded = load_allowlist_profile(None)
    assert loaded == ORCA_DEVNET_ALLOWLIST


def test_load_allowlist_profile_returns_deep_copy():
    """Mutation of the return value must NOT poison the module-level constant."""
    from src.policy.allowlists import ORCA_DEVNET_ALLOWLIST, load_allowlist_profile

    first = load_allowlist_profile(None)
    first["programs"].append("EVIL_PROGRAM")
    first["programs"].clear()
    # Re-load — default must be intact.
    second = load_allowlist_profile(None)
    assert second == ORCA_DEVNET_ALLOWLIST
    assert "EVIL_PROGRAM" not in second["programs"]
    # Sanity: the constant itself is untouched.
    assert "EVIL_PROGRAM" not in ORCA_DEVNET_ALLOWLIST["programs"]
    assert len(ORCA_DEVNET_ALLOWLIST["programs"]) == 6


def test_load_allowlist_profile_reads_json_file(tmp_path):
    import json as _json

    alternate = {"programs": ["AAA", "BBB"]}
    p = tmp_path / "alt.json"
    p.write_text(_json.dumps(alternate), encoding="utf-8")

    from src.policy.allowlists import load_allowlist_profile

    loaded = load_allowlist_profile(str(p))
    assert loaded == alternate


def test_load_allowlist_profile_missing_file_raises(tmp_path):
    from src.policy.allowlists import load_allowlist_profile
    from src.policy.engine import PolicyEngineError

    with pytest.raises(PolicyEngineError) as ei:
        load_allowlist_profile(str(tmp_path / "does-not-exist.json"))
    assert "allowlist" in str(ei.value).lower() or "not found" in str(ei.value).lower()


def test_load_allowlist_profile_malformed_json_raises(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not: valid json", encoding="utf-8")

    from src.policy.allowlists import load_allowlist_profile
    from src.policy.engine import PolicyEngineError

    with pytest.raises(PolicyEngineError):
        load_allowlist_profile(str(p))


# --- build_wallet_policy extensions (Task 10.2) --------------------------


def test_build_wallet_policy_default_action_is_deny():
    from src.policy.allowlists import ORCA_DEVNET_ALLOWLIST
    from src.policy.engine import InstancePolicyEngine

    engine = InstancePolicyEngine()
    policy = engine.build_wallet_policy(
        spec=_valid_spec(),
        allowlist_profile=ORCA_DEVNET_ALLOWLIST,
        chain="devnet",
    )
    assert policy["default_action"] == "DENY"


def test_build_wallet_policy_transfer_cap_uses_max_position_size():
    from src.policy.allowlists import ORCA_DEVNET_ALLOWLIST
    from src.policy.engine import InstancePolicyEngine

    engine = InstancePolicyEngine()
    spec = _valid_spec()
    spec["max_position_size"] = 123_456_789

    policy = engine.build_wallet_policy(
        spec=spec,
        allowlist_profile=ORCA_DEVNET_ALLOWLIST,
        chain="devnet",
    )
    assert policy["transfer_cap"] == {
        "instruction": "TransferChecked",
        "max_amount": 123_456_789,
    }


def test_build_wallet_policy_transfer_cap_at_min_boundary():
    """max_position_size = 1 passes validate_spec; transfer_cap must mirror."""
    from src.policy.allowlists import ORCA_DEVNET_ALLOWLIST
    from src.policy.engine import InstancePolicyEngine

    engine = InstancePolicyEngine()
    spec = _valid_spec()
    spec["max_position_size"] = 1

    policy = engine.build_wallet_policy(
        spec=spec,
        allowlist_profile=ORCA_DEVNET_ALLOWLIST,
        chain="devnet",
    )
    assert policy["transfer_cap"]["max_amount"] == 1


def test_build_wallet_policy_preserves_allowlist_profile_as_data():
    """I3 — engine returns caller's profile as data, verbatim, as a copy."""
    from src.policy.engine import InstancePolicyEngine

    engine = InstancePolicyEngine()
    profile = {
        "programs": ["AAA", "BBB"],
        "custom_marker": "xyz",
    }
    policy = engine.build_wallet_policy(
        spec=_valid_spec(),
        allowlist_profile=profile,
        chain="devnet",
    )
    assert policy["allowlist_profile"] == profile
    # Output is a defensive copy — mutating the output must not poison caller.
    policy["allowlist_profile"]["programs"].append("MUTATED")
    assert "MUTATED" not in profile["programs"]


def test_build_wallet_policy_profile_substitution_changes_output():
    """R1 — default profile is not hardcoded inside build_wallet_policy."""
    from src.policy.allowlists import ORCA_DEVNET_ALLOWLIST
    from src.policy.engine import InstancePolicyEngine

    engine = InstancePolicyEngine()
    alt_profile = {"programs": ["ONLY_ONE_PROGRAM"]}

    default_policy = engine.build_wallet_policy(
        spec=_valid_spec(),
        allowlist_profile=ORCA_DEVNET_ALLOWLIST,
        chain="devnet",
    )
    alt_policy = engine.build_wallet_policy(
        spec=_valid_spec(),
        allowlist_profile=alt_profile,
        chain="devnet",
    )
    assert default_policy["allowlist_profile"] != alt_policy["allowlist_profile"]
    assert alt_policy["allowlist_profile"]["programs"] == ["ONLY_ONE_PROGRAM"]


def test_build_wallet_policy_output_has_no_provider_specific_keys():
    """I5/R5 — no Privy-native keys in the provider-agnostic engine output.

    Privy's policy HTTP shape is {rules: [...], default_action, ...}. The
    engine must NOT produce `rules`, `action`, `solana_program_instruction`,
    or `SolanaTokenProgramInstructionCondition` at its top level. Those
    belong at the wallet-service translation boundary.
    """
    from src.policy.allowlists import ORCA_DEVNET_ALLOWLIST
    from src.policy.engine import InstancePolicyEngine

    engine = InstancePolicyEngine()
    policy = engine.build_wallet_policy(
        spec=_valid_spec(),
        allowlist_profile=ORCA_DEVNET_ALLOWLIST,
        chain="devnet",
    )
    forbidden = {
        "rules",
        "action",
        "solana_program_instruction",
        "SolanaTokenProgramInstructionCondition",
    }
    assert forbidden.isdisjoint(policy.keys())


def test_build_wallet_policy_refuses_testnet():
    from src.policy.allowlists import ORCA_DEVNET_ALLOWLIST
    from src.policy.engine import InstancePolicyEngine, PolicyEngineError

    engine = InstancePolicyEngine()
    with pytest.raises(PolicyEngineError):
        engine.build_wallet_policy(
            spec=_valid_spec(),
            allowlist_profile=ORCA_DEVNET_ALLOWLIST,
            chain="testnet",
        )


def test_build_wallet_policy_refuses_empty_chain():
    from src.policy.allowlists import ORCA_DEVNET_ALLOWLIST
    from src.policy.engine import InstancePolicyEngine, PolicyEngineError

    engine = InstancePolicyEngine()
    with pytest.raises(PolicyEngineError):
        engine.build_wallet_policy(
            spec=_valid_spec(),
            allowlist_profile=ORCA_DEVNET_ALLOWLIST,
            chain="",
        )

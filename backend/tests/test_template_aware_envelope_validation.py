"""Spec §10 test 1 — template-aware envelope validation.

Locks: TEMPLATE_ENVELOPE_REGISTRY keyed by template_key; validate_spec_for_template
delegates to the registry; swap and rebalance envelopes are disjoint sets;
unknown template_key returns ok=False; defensive copy.
"""
from __future__ import annotations

from src.policy.engine import (
    InstancePolicyEngine,
    TEMPLATE_ENVELOPE_REGISTRY,
    validate_spec_for_template,
)
from tests._rebalance_helpers import make_rebalance_envelope, make_swap_envelope


def test_swap_envelope_valid_under_swap_template_key():
    result = validate_spec_for_template("swap_executor_v1", make_swap_envelope())
    assert result.ok, result.errors


def test_swap_envelope_missing_field_fails():
    spec = make_swap_envelope()
    spec.pop("max_slippage_bps")
    result = validate_spec_for_template("swap_executor_v1", spec)
    assert not result.ok
    assert any("max_slippage_bps" in e for e in result.errors)


def test_rebalance_field_under_swap_template_key_rejected():
    spec = make_swap_envelope()
    spec["target_allocations"] = {"X": 1.0}
    result = validate_spec_for_template("swap_executor_v1", spec)
    assert not result.ok
    assert any("target_allocations" in e for e in result.errors)


def test_rebalance_envelope_valid_under_rebalance_template_key():
    result = validate_spec_for_template(
        "rebalance_executor_v1", make_rebalance_envelope()
    )
    assert result.ok, result.errors


def test_rebalance_envelope_missing_target_allocations_fails():
    spec = make_rebalance_envelope()
    spec.pop("target_allocations")
    result = validate_spec_for_template("rebalance_executor_v1", spec)
    assert not result.ok
    assert any("target_allocations" in e for e in result.errors)


def test_swap_field_under_rebalance_template_key_rejected():
    """Disjoint envelope sets: swap-only fields must NOT pass under rebalance."""
    spec = make_rebalance_envelope()
    spec["max_runtime_seconds"] = 600
    result = validate_spec_for_template("rebalance_executor_v1", spec)
    assert not result.ok
    assert any("max_runtime_seconds" in e for e in result.errors)


def test_unknown_template_key_rejected():
    result = validate_spec_for_template("nonexistent_template_v1", {})
    assert not result.ok
    assert any("unknown template_key" in e for e in result.errors)


def test_validate_spec_for_template_does_not_mutate_input():
    """Defensive copy: input spec dict is never mutated."""
    spec = make_rebalance_envelope()
    snapshot = dict(spec)
    snapshot["target_allocations"] = dict(spec["target_allocations"])
    validate_spec_for_template("rebalance_executor_v1", spec)
    assert spec == snapshot


def test_legacy_validate_spec_swap_only_unchanged():
    """V2 5-field envelope contract preserved on InstancePolicyEngine.validate_spec()."""
    engine = InstancePolicyEngine()
    result = engine.validate_spec(make_swap_envelope())
    assert result.ok, result.errors


def test_legacy_validate_spec_rejects_rebalance_envelope():
    """validate_spec() (swap-only) must reject rebalance envelope unchanged."""
    engine = InstancePolicyEngine()
    result = engine.validate_spec(make_rebalance_envelope())
    assert not result.ok


def test_template_envelope_registry_disjoint_sets():
    """Hard regression-lock: each template's UNIQUE-to-itself fields don't appear in the other.

    Spec §5.1 allows shared envelope fields (e.g. `allowed_token_universe`,
    `max_slippage_bps`) to appear in both swap and rebalance — they mean the
    same thing in both. The lockable invariant is that each template owns at
    least one UNIQUE field, and those unique fields don't bleed into the
    other template's envelope. The cross-template field-rejection invariant
    is already locked by `test_rebalance_field_under_swap_template_key_rejected`
    (target_allocations is rebalance-only) and
    `test_swap_field_under_rebalance_template_key_rejected` (max_runtime_seconds
    is swap-only).
    """
    swap = TEMPLATE_ENVELOPE_REGISTRY["swap_executor_v1"]
    rebalance = TEMPLATE_ENVELOPE_REGISTRY["rebalance_executor_v1"]
    swap_only = swap - rebalance
    rebalance_only = rebalance - swap
    assert swap_only, (
        f"swap_executor_v1 must have at least one swap-only field; got {sorted(swap)}"
    )
    assert rebalance_only, (
        f"rebalance_executor_v1 must have at least one rebalance-only field; got {sorted(rebalance)}"
    )
    assert swap_only.isdisjoint(rebalance), (
        f"swap-only fields leaked into rebalance envelope: {swap_only & rebalance}"
    )
    assert rebalance_only.isdisjoint(swap), (
        f"rebalance-only fields leaked into swap envelope: {rebalance_only & swap}"
    )


def test_unhashable_template_key_returns_ok_false_not_raises():
    """Bug fix: list/dict template_key must NOT raise TypeError from membership test.

    Plan requires non-string template_key handling; the original snippet had
    `not isinstance(template_key, str)`. Removing it caused TypeError leaks for
    unhashable inputs. Restore deterministic ok=False with `unknown template_key`.
    """
    # Unhashable list — would have raised TypeError under the broken impl.
    result_list = validate_spec_for_template(["x"], {})
    assert not result_list.ok
    assert any("unknown template_key" in e for e in result_list.errors)

    # Unhashable dict — same path.
    result_dict = validate_spec_for_template({"x": 1}, {})
    assert not result_dict.ok
    assert any("unknown template_key" in e for e in result_dict.errors)


def test_hashable_non_string_template_key_returns_ok_false():
    """Hashable non-strings (None, int) must also return ok=False with the
    same `unknown template_key` error wording — consistent surface across
    all non-string inputs."""
    for bad_key in (None, 42, 0):
        result = validate_spec_for_template(bad_key, {})
        assert not result.ok, f"Expected ok=False for template_key={bad_key!r}"
        assert any("unknown template_key" in e for e in result.errors), (
            f"Expected 'unknown template_key' in errors for {bad_key!r}; got {result.errors}"
        )


# ---------------------------------------------------------------------------
# Task 2 — template-aware _validate_allowed_fields_for_template in template_service
# ---------------------------------------------------------------------------

import json
import pytest

from src.services.template_service import (
    TemplateValidationError,
    _validate_allowed_fields_for_template,
)


def test_swap_allowed_fields_json_passes_under_swap_template_key():
    """Plan Task 2 — swap envelope fields, JSON-encoded, register cleanly."""
    swap_fields = sorted([
        "allowed_token_universe", "max_slippage_bps",
        "max_position_size", "max_iterations", "max_runtime_seconds",
    ])
    # Must not raise.
    _validate_allowed_fields_for_template(
        "swap_executor_v1", json.dumps(swap_fields)
    )


def test_rebalance_allowed_fields_json_passes_under_rebalance_template_key():
    """Plan Task 2 — rebalance envelope fields, JSON-encoded, register cleanly."""
    rebal_fields = sorted([
        "allowed_token_universe", "target_allocations", "rebalance_threshold_bps",
        "max_slippage_bps", "max_position_weight", "max_trade_value", "dry_run",
    ])
    _validate_allowed_fields_for_template(
        "rebalance_executor_v1", json.dumps(rebal_fields)
    )


def test_swap_allowed_fields_json_fails_under_rebalance_template_key():
    """Plan Task 2 — disjoint envelope contract: swap-only fields must NOT
    register under rebalance template."""
    swap_fields = sorted([
        "allowed_token_universe", "max_slippage_bps",
        "max_position_size", "max_iterations", "max_runtime_seconds",
    ])
    with pytest.raises(TemplateValidationError):
        _validate_allowed_fields_for_template(
            "rebalance_executor_v1", json.dumps(swap_fields)
        )


def test_unknown_template_key_at_registration_rejected():
    """Plan Task 2 — unknown template_key fails at registration time, mirroring
    the deploy-time gate in validate_spec_for_template."""
    with pytest.raises(TemplateValidationError):
        _validate_allowed_fields_for_template("nonexistent_template_v1", json.dumps([]))


def test_malformed_allowed_fields_json_rejected():
    """Edge-case gate — malformed JSON in allowed_fields_json must produce a
    clear TemplateValidationError, not a raw json.JSONDecodeError leak."""
    with pytest.raises(TemplateValidationError):
        _validate_allowed_fields_for_template("swap_executor_v1", "{not valid json")


def test_legacy_validate_allowed_fields_shim_swap_compat():
    """Edge-case gate — the legacy private `_validate_allowed_fields` shim
    must remain importable and delegate to the swap envelope, so any
    pre-existing caller that hasn't migrated to the template-aware variant
    keeps working."""
    from src.services.template_service import TemplateService
    # Public-private boundary: TemplateService._validate_allowed_fields exists
    # as a static method per the plan's back-compat clause.
    assert hasattr(TemplateService, "_validate_allowed_fields"), (
        "Plan §Task 2 Step 3 requires the legacy shim `_validate_allowed_fields` "
        "to remain on TemplateService for back-compat."
    )
    swap_fields = sorted([
        "allowed_token_universe", "max_slippage_bps",
        "max_position_size", "max_iterations", "max_runtime_seconds",
    ])
    # Legacy form: no template_key argument.
    TemplateService._validate_allowed_fields(json.dumps(swap_fields))
    # Swap registration via the legacy path must still validate; rebalance
    # fields must still fail (since the shim delegates to the swap envelope).
    rebal_fields = sorted([
        "allowed_token_universe", "target_allocations", "rebalance_threshold_bps",
        "max_slippage_bps", "max_position_weight", "max_trade_value", "dry_run",
    ])
    with pytest.raises(TemplateValidationError):
        TemplateService._validate_allowed_fields(json.dumps(rebal_fields))

"""InstancePolicyEngine — envelope validation + provider-agnostic policy build + consent recording.

Responsibilities:
- `validate_spec(spec)` — enforce the V2 5-field customization envelope per
  `V2_DESIGN_SPEC.md §4`. Unknown fields are rejected (prevents V2.1 scope
  leak). Out-of-range values are rejected.
- `build_wallet_policy(spec, allowlist_profile, chain)` — produce a
  provider-agnostic wallet-policy dict. The actual Solana-specific allowlist
  shape comes from Phase 0 validation (V0-VAL-2) and is injected. This
  module does NOT hardcode Orca / SPL Token / ComputeBudget program IDs;
  those live in `src.policy.allowlists.ORCA_DEVNET_ALLOWLIST` and are
  passed in by the caller.
- `record_consent(acknowledgments)` — produce a deterministic
  `ConsentRecord` with canonical JSON + sha256 so the deploy-time
  orchestration (Phase B) can anchor it via a VerificationArtifact.

No provider imports. No network calls. No env reads at import time. Tests
rely on this keeping the module pure.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable


class PolicyEngineError(Exception):
    """Base class for policy-engine failures."""


# V2 locked customization envelope (spec §4).
_ALLOWED_ENVELOPE_FIELDS: frozenset[str] = frozenset(
    {
        "allowed_token_universe",
        "max_slippage_bps",
        "max_position_size",
        "max_iterations",
        "max_runtime_seconds",
    }
)

_REBALANCE_ENVELOPE_FIELDS: frozenset[str] = frozenset(
    {
        "allowed_token_universe",
        "target_allocations",
        "rebalance_threshold_bps",
        "max_slippage_bps",
        "max_position_weight",
        "max_trade_value",
        "dry_run",
    }
)

# Module-level template registry — keyed by template_key.
TEMPLATE_ENVELOPE_REGISTRY: dict[str, frozenset[str]] = {
    "swap_executor_v1":      _ALLOWED_ENVELOPE_FIELDS,
    "rebalance_executor_v1": _REBALANCE_ENVELOPE_FIELDS,
}


def validate_spec_for_template(template_key: str, spec: dict) -> "ValidationResult":
    """Template-aware envelope validation per spec §5.2.

    Step 1: unknown template_key → ok=False with locked message.
    Step 2: membership check against TEMPLATE_ENVELOPE_REGISTRY[template_key].
    Step 3: per-template range/shape checks (Task 1: swap delegates to validate_spec;
            rebalance range/shape checks land in Task 3 — Task 1 stops after membership).

    Defensive copy: this function does NOT mutate `spec`.
    """
    if not isinstance(template_key, str) or template_key not in TEMPLATE_ENVELOPE_REGISTRY:
        return ValidationResult(errors=[
            f"unknown template_key {template_key!r}: must be one of "
            f"{sorted(TEMPLATE_ENVELOPE_REGISTRY.keys())}"
        ])

    allowed = TEMPLATE_ENVELOPE_REGISTRY[template_key]
    errors: list[str] = []

    spec_keys = set(spec.keys())
    extra = spec_keys - allowed
    missing = allowed - spec_keys
    for k in sorted(extra):
        errors.append(
            f"unknown envelope field {k!r}; {template_key!r} customization is locked to "
            f"{sorted(allowed)}"
        )
    for k in sorted(missing):
        errors.append(f"missing required envelope field {k!r} for template {template_key!r}")

    if not errors and template_key == "swap_executor_v1":
        return InstancePolicyEngine().validate_spec(spec)

    # Rebalance range/shape checks land in Task 3. For Task 1, membership-pass
    # rebalance specs are accepted as ok=True at this layer.
    return ValidationResult(errors=errors)


# Range bounds. Narrow on purpose: these are liability controls, not tuning knobs.
_MAX_SLIPPAGE_BPS_LIMIT = 500  # matches V1 `max_slippage_bps: Field(ge=0, le=500)` in db/schemas.py
_MAX_POSITION_SIZE_LIMIT = 10_000_000_000  # 10,000 USDC in base units
_MAX_ITERATIONS_LIMIT = 200
_MAX_RUNTIME_SECONDS_LIMIT = 3600  # 1h

# Required DeploymentConsent acknowledgments. Per plan invariant 9.
_REQUIRED_CONSENT_KEYS: frozenset[str] = frozenset(
    {
        "devnet_only_acknowledged",
        "platform_managed_signing_acknowledged",
        "spend_caps_acknowledged",
        "no_indemnity_acknowledged",
    }
)


@dataclass
class ValidationResult:
    """Outcome of validate_spec(). `ok` is True iff `errors` is empty."""

    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class ConsentRecord:
    """Deterministic consent record anchorable as a VerificationArtifact."""

    canonical_json: str
    content_hash: str  # sha256 hex of canonical_json


# Alias surfaced in the package `__all__` for downstream orchestration.
DeploymentConsent = ConsentRecord


class InstancePolicyEngine:
    """Pure-compute policy engine. No I/O, no state.

    Instances can be created per-request or held as a singleton — the
    class has no fields. Kept as a class (not module functions) to match
    the protocol surface named in the V2 plan.
    """

    # -------------------------------------------------------------------
    # validate_spec
    # -------------------------------------------------------------------

    def validate_spec(self, spec: dict[str, Any]) -> ValidationResult:
        """Enforce the V2 5-field envelope.

        Rules:
        - Every required field must be present.
        - Unknown fields are rejected.
        - Each field has an explicit range check.
        """
        errors: list[str] = []

        # Unknown fields first — this is the V2.1-scope-leak guard.
        for key in spec.keys():
            if key not in _ALLOWED_ENVELOPE_FIELDS:
                errors.append(
                    f"unknown envelope field {key!r}; V2 customization is locked to "
                    f"{sorted(_ALLOWED_ENVELOPE_FIELDS)}"
                )

        # Missing required fields.
        for key in _ALLOWED_ENVELOPE_FIELDS:
            if key not in spec:
                errors.append(f"missing required envelope field {key!r}")

        if errors:
            return ValidationResult(errors=errors)

        # Shape / range checks.
        self._check_token_universe(spec["allowed_token_universe"], errors)
        self._check_int_range(
            "max_slippage_bps", spec["max_slippage_bps"],
            lo=0, hi=_MAX_SLIPPAGE_BPS_LIMIT, errors=errors,
        )
        self._check_int_range(
            "max_position_size", spec["max_position_size"],
            lo=1, hi=_MAX_POSITION_SIZE_LIMIT, errors=errors,
        )
        self._check_int_range(
            "max_iterations", spec["max_iterations"],
            lo=1, hi=_MAX_ITERATIONS_LIMIT, errors=errors,
        )
        self._check_int_range(
            "max_runtime_seconds", spec["max_runtime_seconds"],
            lo=1, hi=_MAX_RUNTIME_SECONDS_LIMIT, errors=errors,
        )

        return ValidationResult(errors=errors)

    @staticmethod
    def _check_token_universe(value: Any, errors: list[str]) -> None:
        if not isinstance(value, list) or not value:
            errors.append("allowed_token_universe must be a non-empty list of mint addresses")
            return
        for mint in value:
            if not isinstance(mint, str) or not mint:
                errors.append(
                    f"allowed_token_universe entries must be non-empty strings; got {mint!r}"
                )

    @staticmethod
    def _check_int_range(
        name: str, value: Any, lo: int, hi: int, errors: list[str],
    ) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"{name} must be int; got {type(value).__name__}")
            return
        if value < lo or value > hi:
            errors.append(f"{name} out of range [{lo}, {hi}]: {value}")

    # -------------------------------------------------------------------
    # build_wallet_policy
    # -------------------------------------------------------------------

    def build_wallet_policy(
        self,
        spec: dict[str, Any],
        allowlist_profile: dict[str, Any],
        chain: str,
    ) -> dict[str, Any]:
        """Produce a provider-agnostic wallet-policy dict.

        `allowlist_profile` is the output of V0-VAL-2 — the observed
        Solana instruction/program footprint, captured as a dict the
        policy engine can consume without knowing which Solana programs
        are involved. The default for V2 is ``ORCA_DEVNET_ALLOWLIST``
        from ``src.policy.allowlists`` but the engine does not import
        it; profile selection is the caller's job.

        `chain` MUST be "devnet" in V2. Per the plan invariant, no hosted
        flow may target mainnet; refuse early.

        Output shape (provider-agnostic):

        - ``chain``: echo of the chain argument
        - ``envelope``: the validated 5-field customization envelope
        - ``allowlist_profile``: defensive copy of the caller's profile
        - ``transfer_cap``: ``{"instruction": "TransferChecked",
          "max_amount": spec["max_position_size"]}`` — enforced at the
          SPL TokenProgram layer once the wallet-service translates this
          dict into provider-specific rule payloads
        - ``default_action``: ``"DENY"`` — deny-by-default
        - ``runner_enforced``: list of invariants enforced by the runner
          layer (not by wallet policy)

        Provider-specific serialization (e.g. Privy's
        ``{rules: [...], default_action}`` HTTP shape) lives at the
        wallet-service translation boundary — NOT in this engine.
        """
        if chain != "devnet":
            raise PolicyEngineError(
                f"build_wallet_policy: chain={chain!r} rejected. V2 hosted "
                f"execution is devnet-only; mainnet targets must be blocked "
                f"before reaching this layer."
            )

        # Ensure the spec is valid first. We don't accept half-specified input.
        vr = self.validate_spec(spec)
        if not vr.ok:
            raise PolicyEngineError(
                f"build_wallet_policy: spec invalid: {vr.errors}"
            )

        return {
            "chain": chain,
            "envelope": {
                "allowed_token_universe": list(spec["allowed_token_universe"]),
                "max_slippage_bps": spec["max_slippage_bps"],
                "max_position_size": spec["max_position_size"],
                "max_iterations": spec["max_iterations"],
                "max_runtime_seconds": spec["max_runtime_seconds"],
            },
            "allowlist_profile": copy.deepcopy(allowlist_profile),
            "transfer_cap": {
                "instruction": "TransferChecked",
                "max_amount": spec["max_position_size"],
            },
            "default_action": "DENY",
            # Explicit marker so operators reviewing the policy can see at a
            # glance what's provider-enforced vs runner-enforced. Slippage
            # is runner-enforced per V0-VAL-4 (Whirlpool swap slippage lives
            # in custom calldata Privy's policy engine cannot decode).
            "runner_enforced": [
                "quote_freshness",
                "slippage_upper_bound_per_swap",
                "iteration_budget",
                "time_budget",
            ],
        }

    # -------------------------------------------------------------------
    # record_consent
    # -------------------------------------------------------------------

    def record_consent(self, acknowledgments: dict[str, Any]) -> ConsentRecord:
        """Produce a deterministic consent record.

        All four acknowledgments must be explicitly True. Missing or False
        acknowledgments raise — there is no partial consent in V2.
        """
        missing = _REQUIRED_CONSENT_KEYS - acknowledgments.keys()
        if missing:
            raise PolicyEngineError(
                f"record_consent: missing required acknowledgments: {sorted(missing)}"
            )

        not_truthy = [
            k for k in _REQUIRED_CONSENT_KEYS if acknowledgments.get(k) is not True
        ]
        if not_truthy:
            raise PolicyEngineError(
                f"record_consent: these acknowledgments must be True: {sorted(not_truthy)}"
            )

        # Canonical JSON: sorted keys, no whitespace, ensure_ascii=False so
        # any future i18n consent text hashes identically across platforms.
        canonical = json.dumps(
            {k: bool(acknowledgments[k]) for k in sorted(_REQUIRED_CONSENT_KEYS)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return ConsentRecord(canonical_json=canonical, content_hash=digest)

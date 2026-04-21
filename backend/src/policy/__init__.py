"""V2 instance policy package.

Exports `InstancePolicyEngine`, which validates customization specs against
the V2 5-field envelope, builds a provider-agnostic wallet policy
parameterized by a Phase-0-derived `allowlist_profile`, and records
deployment consent as a hashable record suitable for anchoring in a
VerificationArtifact.
"""

from src.policy.engine import (
    ConsentRecord,
    DeploymentConsent,
    InstancePolicyEngine,
    PolicyEngineError,
    ValidationResult,
)

__all__ = [
    "ConsentRecord",
    "DeploymentConsent",
    "InstancePolicyEngine",
    "PolicyEngineError",
    "ValidationResult",
]

"""InstanceRuntime — provider-agnostic protocol for V2 hosted instances.

Design goals:
- No provider-specific imports. AgentOS / Privy / httpx / solders all stay
  out of this module so tests can import it without any runtime state.
- `isinstance()` must work (@runtime_checkable) so callers can fail fast
  when an implementation is missing required methods.
- The protocol surface is exactly three methods: deploy, invoke_decide,
  teardown. Anything more is Phase B concrete-runtime concern, not P0.

Implementations must live in a separate module (e.g. `src/runtime/agentos.py`)
so the single permitted AgentOS SDK import stays localised per V2 plan
invariant 4 ("Runtime import boundary").

`InstanceSpec` and `InstanceHandle` are intentionally thin. They are
dataclasses carrying the contract between the policy engine and a runtime;
the runtime may carry additional private state in `InstanceHandle.extra`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class InstanceSpec:
    """Validated spec passed into a runtime's deploy()."""

    template_key: str
    template_version: str
    effective_config: dict[str, Any]
    instance_owner_ref: str


@dataclass
class InstanceHandle:
    """Opaque handle to a running instance.

    Deliberately a dataclass instead of a bare string: concrete runtimes
    may need to carry extra provider-specific state (e.g. AgentOS session
    IDs) which must not leak into shared backend code.
    """

    instance_id: str
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class InstanceRuntime(Protocol):
    """Protocol for a V2 hosted-instance runtime.

    Any concrete implementation (AgentOS-backed, a mock, or a future
    alternative) MUST provide these three async methods with the exact
    signatures below.
    """

    async def deploy(self, spec: InstanceSpec) -> InstanceHandle:
        """Provision a running instance for `spec`. Returns an opaque handle."""
        ...

    async def invoke_decide(self, handle: InstanceHandle, state: Any) -> Any:
        """Call the instance's decision function with a ChallengeState.

        Return type is AgentAction (defined in src.challenges.base). Kept
        as `Any` here to avoid importing the V1 challenge module from the
        protocol module, preserving the provider-agnostic boundary.
        """
        ...

    async def teardown(self, handle: InstanceHandle) -> None:
        """Release resources held by the instance. Idempotent."""
        ...

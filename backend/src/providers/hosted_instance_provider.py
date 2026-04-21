"""HostedInstanceProvider — bridge from a V2 hosted runtime into the V1
AgentDecisionProvider protocol.

Keeps the V1 runner path intact: RunnerService.execute_run() accepts any
AgentDecisionProvider, so V2 hosted instances flow through the exact same
observe → decide → validate → execute → persist loop as V1 local agents.

This module is provider-agnostic on purpose. No AgentOS imports, no Privy
imports — it only talks to an `InstanceRuntime` protocol. Concrete
runtime implementations (e.g. `src/runtime/agentos.py`) satisfy the
protocol and plug in here.
"""

from __future__ import annotations

from typing import Any

from src.challenges.base import ChallengeState
from src.db.schemas import AgentAction
from src.providers.base import AgentDecisionProvider
from src.runtime.base import InstanceHandle, InstanceRuntime


class HostedInstanceError(Exception):
    """Raised when HostedInstanceProvider is constructed or used incorrectly."""


class HostedInstanceProvider(AgentDecisionProvider):
    """AgentDecisionProvider whose decide() calls run through an InstanceRuntime.

    Construction is fail-closed: a missing runtime is a configuration bug,
    not a runtime recoverable error. Mirrors the V1 pattern where
    ChallengeService._require_program() raises OnchainError when the
    program client is unavailable.
    """

    def __init__(self, runtime: InstanceRuntime, handle: InstanceHandle) -> None:
        if runtime is None:
            raise HostedInstanceError(
                "HostedInstanceProvider requires a non-None runtime. "
                "V2 hosted benchmarking cannot proceed without an InstanceRuntime "
                "implementation — see V2 plan §3 (same-runtime benchmark invariant)."
            )
        if handle is None:
            raise HostedInstanceError(
                "HostedInstanceProvider requires a non-None handle; the runtime "
                "must return an InstanceHandle from deploy() before decide() runs."
            )
        self.runtime = runtime
        self.handle = handle

    async def decide(self, state: ChallengeState) -> AgentAction:
        result: Any = await self.runtime.invoke_decide(self.handle, state)
        # The runtime contract says invoke_decide returns an AgentAction.
        # Anchor that at the bridge boundary so upstream callers (runner +
        # validator) see a real AgentAction regardless of runtime impl.
        if not isinstance(result, AgentAction):
            raise HostedInstanceError(
                f"runtime.invoke_decide returned {type(result).__name__}, "
                f"expected AgentAction. Runtime implementation is violating "
                f"the InstanceRuntime contract."
            )
        return result

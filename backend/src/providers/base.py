"""AgentDecisionProvider protocol — the interface for strategy decision-making.

Agno boundary: The provider decides within constraints.
Agent Arena owns: challenge definition, execution orchestration, validation,
settlement, evidence storage, scoring, public reputation.

The provider must NOT decide: completion validity, settlement truth,
winner determination, or canonical benchmark storage.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.challenges.base import ChallengeState
from src.db.schemas import AgentAction


@runtime_checkable
class AgentDecisionProvider(Protocol):
    """Protocol for strategy decision providers.

    V1 implementation: LocalAgentProvider (Agno Agent with submitted
    system_prompt, fixed model from challenge config, temperature=0).

    V2 will add: ExternalWebhookProvider, OpenClaw adapters, etc.
    """

    async def decide(self, state: ChallengeState) -> AgentAction:
        """Given the current challenge state, return the next action.

        Args:
            state: ChallengeState containing portfolio balances,
                   completed swaps, required swaps, iterations used, etc.

        Returns:
            An AgentAction with type (EXECUTE_SWAP | WAIT | FINISH)
            and validated params.
        """
        ...

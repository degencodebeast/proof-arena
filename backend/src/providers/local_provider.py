"""LocalAgentProvider — V1 implementation of AgentDecisionProvider.

Wraps an Agno Agent with submitted system_prompt and fixed model.
Formats ChallengeState into a decision prompt, runs the agent,
and parses the response into a validated AgentAction.
"""

from __future__ import annotations

import json
import logging
import re

from agno.agent import Agent

from src.agents.arena_agent import create_arena_agent
from src.challenges.base import ChallengeState
from src.db.schemas import AgentAction, AgentActionType

logger = logging.getLogger(__name__)


class ActionParseError(Exception):
    """Raised when agent response cannot be parsed into a valid AgentAction."""

    def __init__(self, raw_response: str, detail: str):
        self.raw_response = raw_response
        self.detail = detail
        super().__init__(f"Failed to parse action: {detail}")


class LocalAgentProvider:
    """V1 AgentDecisionProvider — Agno Agent with submitted strategy.

    Implements the decide(state: ChallengeState) -> AgentAction protocol.
    """

    def __init__(
        self,
        system_prompt: str,
        config: dict,
        llm_provider: str,
        llm_model: str,
        tools: list,
    ):
        self.system_prompt = system_prompt
        self.config = config
        self.agent: Agent = create_arena_agent(
            system_prompt=system_prompt,
            llm_provider=llm_provider,
            llm_model=llm_model,
            tools=tools,
        )

    async def decide(self, state: ChallengeState) -> AgentAction:
        """Given challenge state, return the next action.

        1. Format state into a decision prompt
        2. Run the Agno agent
        3. Parse response into AgentAction
        """
        prompt = self._format_state_prompt(state)

        response = await self.agent.arun(prompt)

        raw_content = ""
        if response and response.content:
            raw_content = response.content
        elif response and response.messages:
            # Fallback: concatenate assistant messages
            for msg in response.messages:
                if hasattr(msg, "content") and msg.content:
                    raw_content += str(msg.content)

        return self._parse_action(raw_content)

    @staticmethod
    def _format_state_prompt(state: ChallengeState) -> str:
        """Format ChallengeState into a structured decision prompt.

        The prompt gives the agent all information needed to decide
        the next action: current portfolio, completed/required swaps,
        budget remaining, and the action format.
        """
        return f"""Current benchmark state:

Portfolio balances: {json.dumps(state.portfolio)}
Completed swaps: {json.dumps(state.completed_swaps)}
Required swaps remaining: {json.dumps(state.required_swaps)}
Iterations used: {state.iterations_used} / {state.iteration_budget}
Time elapsed: {state.elapsed_secs:.1f}s / {state.time_budget_secs}s
Status: {state.status}

Choose your next action. Respond with EXACTLY ONE of these JSON formats:

1. Execute a swap:
{{"type": "EXECUTE_SWAP", "params": {{"quote_id": "<quote_id>", "max_slippage_bps": <number>}}}}

2. Wait before next action:
{{"type": "WAIT", "params": {{"seconds": <1-60>}}}}

3. Finish execution:
{{"type": "FINISH", "params": {{}}}}

Respond with ONLY the JSON action, no explanation."""

    @staticmethod
    def _parse_action(raw_response: str) -> AgentAction:
        """Parse agent response into a validated AgentAction.

        Strict parsing order:
        1. Direct JSON parse (full response is JSON)
        2. JSON in markdown code blocks (```json ... ```)
        3. Deepest JSON object extraction (handles nested params)

        NO natural language fallback. The agent is explicitly instructed
        to respond with JSON only. If it doesn't, that's an error — not
        a signal to guess intent from prose words like "done" or "complete".
        """
        if not raw_response or not raw_response.strip():
            raise ActionParseError(raw_response, "Empty response from agent")

        text = raw_response.strip()

        # Try 1: Direct JSON parse
        parsed = _try_parse_action_json(text)
        if parsed is not None:
            return parsed

        # Try 2: Extract JSON from markdown code blocks
        # Use DOTALL to match across lines, non-greedy within block
        block_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if block_match:
            parsed = _try_parse_action_json(block_match.group(1).strip())
            if parsed is not None:
                return parsed

        # Try 3: Find JSON objects in text (including nested braces)
        # Use a brace-depth parser to extract complete JSON objects
        for candidate in _extract_json_objects(text):
            parsed = _try_parse_action_json(candidate)
            if parsed is not None:
                return parsed

        raise ActionParseError(
            raw_response,
            "Could not parse action from response. Expected JSON with "
            "'type' (EXECUTE_SWAP/WAIT/FINISH) and 'params'.",
        )


def _try_parse_action_json(text: str) -> AgentAction | None:
    """Try to parse text as an AgentAction JSON. Returns None on failure."""
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "type" in data:
            return AgentAction(**data)
    except (json.JSONDecodeError, Exception):
        pass
    return None


def _extract_json_objects(text: str) -> list[str]:
    """Extract complete JSON objects from text using brace-depth tracking.

    Handles nested objects like {"type": "EXECUTE_SWAP", "params": {"quote_id": "x"}}.
    """
    objects = []
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                objects.append(text[start : i + 1])
                start = -1
    return objects

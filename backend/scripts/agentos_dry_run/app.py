"""Minimal throwaway AgentOS app for the pre-Task-13 live dry-run.

Exactly one pre-registered agent, SQLite DB under /tmp, served on
localhost:7777. No auth. One file, no reuse past the gate.

Usage:
    OPENROUTER_API_KEY=... python -m scripts.agentos_dry_run.app

From the backend/ dir with the venv activated. Ctrl-C to stop.
"""

from __future__ import annotations

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.models.openrouter import OpenRouter
from agno.os import AgentOS


# Cheap, widely-available OpenRouter model. Any chat-completion model works
# for the round-trip. The round-trip is about SDK payload shape, not model
# quality.
_MODEL_ID = "openai/gpt-4o-mini"

# Pre-registered canonical agent. This mirrors the V2 Proof Arena pattern:
# one agent per template, sessions carry per-instance isolation.
_agent = Agent(
    id="dry-run-agent",
    name="Dry Run Agent",
    model=OpenRouter(id=_MODEL_ID),
    db=AsyncSqliteDb(db_file="/tmp/agentos_dry_run.db"),
    instructions=[
        "You are a test agent for Proof Arena's Task 12 runtime wrapper.",
        'Respond with EXACTLY one JSON object: {"type": "<X>", "params": {...}}.',
        'The "type" field MUST be one of: EXECUTE_SWAP, WAIT, FINISH. No other values are accepted.',
        'If completed_swaps already covers required_swaps, return {"type": "FINISH", "params": {}}.',
        "Never add prose, preambles, or markdown fences around the JSON.",
    ],
)

agent_os = AgentOS(
    id="proofarena-dry-run",
    description="Pre-Task-13 AgentOS runtime contract validation.",
    agents=[_agent],
)

app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="scripts.agentos_dry_run.app:app", reload=False)

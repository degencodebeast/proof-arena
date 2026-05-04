"""Spec §10 test 13 — rebalance canonical agent is decision-only (Task 5)."""
from __future__ import annotations

import sys
from pathlib import Path

# Make `agentos_app` (sibling of backend/) importable for this test.
# Mirrors test_seed_is_single_source_of_truth.py and test_canonical_template_contract_multi.py.
_AGENT_RANK_ROOT = Path(__file__).resolve().parents[2]
if str(_AGENT_RANK_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_RANK_ROOT))

import pytest


def _build_rebalance_agent():
    from agentos_app.agent import build_canonical_rebalance_executor_agent
    from agentos_app.config import load_settings
    settings = load_settings()
    return build_canonical_rebalance_executor_agent(settings, db=None)


def test_rebalance_agent_tools_is_empty_list():
    """Spec §5.3 + §7.2: tools=[] decision-only invariant.

    Generalized tool calling is a follow-on runtime spec. V0 rebalance agent
    holds no tools, owns no wallet, calls no Orca, executes no swaps.
    """
    agent = _build_rebalance_agent()
    assert agent.tools == [], (
        f"Decision-only invariant violated; rebalance canonical agent must have "
        f"tools=[]; got {agent.tools!r}"
    )


def test_rebalance_agent_id_is_template_key():
    """Agent id must equal the rebalance template_key for AgentOS dispatch."""
    agent = _build_rebalance_agent()
    assert agent.id == "rebalance_executor_v1"


def test_rebalance_agent_instructions_object_identity():
    """Agent.instructions IS the REBALANCE_EXECUTOR_V1_SEED system_prompt
    (not a copy). Locks against silent prompt drift via copy/clone.
    """
    from src.services.template_service import REBALANCE_EXECUTOR_V1_SEED
    agent = _build_rebalance_agent()
    assert agent.instructions is REBALANCE_EXECUTOR_V1_SEED["system_prompt"]


@pytest.mark.parametrize("forbidden", [
    "EXECUTE_SWAP",
    "swap leg",
    "rebalance leg",
    "call tool",
    "tool call",
    "execute the rebalance",
])
def test_rebalance_system_prompt_does_not_instruct_tool_calls(forbidden):
    """Spec §5.3 / §6 non-goal 12 / §12 kill 10 — prompt MUST NOT instruct
    executable tool calling. Case-insensitive substring scan."""
    from src.services.template_service import REBALANCE_EXECUTOR_V1_SEED
    prompt = REBALANCE_EXECUTOR_V1_SEED["system_prompt"]
    assert forbidden.lower() not in prompt.lower(), (
        f"Rebalance system prompt contains forbidden substring {forbidden!r}; "
        f"V0 is decision-only / dry-run. Generalized tool calling is a follow-on."
    )


def test_swap_canonical_agent_factory_unchanged():
    """Regression-lock: swap factory still returns tools=[] agent with the
    locked id. Task 5 must not break the swap factory contract."""
    from agentos_app.agent import build_canonical_swap_executor_agent
    from agentos_app.config import load_settings
    settings = load_settings()
    agent = build_canonical_swap_executor_agent(settings, db=None)
    assert agent.tools == []
    # Swap agent id is `settings.canonical_agent_id` per existing wiring.
    # Until Task 7 lands the multi-template config, that's the singular env var.
    assert agent.id == settings.canonical_agent_id

"""Spec §10 test 4 — AgentOS app registers both canonical agents (Task 6)."""
from __future__ import annotations

import sys
from pathlib import Path

# Make `agentos_app` (sibling of backend/) importable for this test.
# Mirrors test_seed_is_single_source_of_truth.py +
# test_canonical_template_contract_multi.py +
# test_rebalance_canonical_agent_decision_only.py.
_AGENT_RANK_ROOT = Path(__file__).resolve().parents[2]
if str(_AGENT_RANK_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_RANK_ROOT))


def test_build_agentos_registers_both_canonical_agents():
    """Spec §10 test 4: AgentOS.agents contains exactly 2 canonical agents
    with ids swap_executor_v1 and rebalance_executor_v1."""
    from agentos_app.app import build_agentos
    os_app = build_agentos()
    ids = sorted(a.id for a in os_app.agents)
    assert ids == ["rebalance_executor_v1", "swap_executor_v1"], (
        f"Expected both canonical agents pre-registered; got ids={ids!r}"
    )


def test_both_canonical_agents_preserve_tools_empty_invariant():
    """Spec §7.2 + §10 test 13: tools=[] decision-only invariant on BOTH agents.
    Verified at the AgentOS-boot layer, not just per-factory."""
    from agentos_app.app import build_agentos
    os_app = build_agentos()
    for agent in os_app.agents:
        assert agent.tools == [], (
            f"Decision-only invariant violated; agent {agent.id!r} has "
            f"tools={agent.tools!r}; both canonical agents must have tools=[]"
        )


def test_build_agentos_description_mentions_both_templates():
    """Plan §Task 6 description literal update — should name both template_keys
    so operators reading the AgentOS metadata see what's pre-registered."""
    from agentos_app.app import build_agentos
    os_app = build_agentos()
    desc = os_app.description.lower()
    assert "swap_executor_v1" in desc, (
        f"Description must mention swap_executor_v1; got {os_app.description!r}"
    )
    assert "rebalance_executor_v1" in desc, (
        f"Description must mention rebalance_executor_v1; got {os_app.description!r}"
    )

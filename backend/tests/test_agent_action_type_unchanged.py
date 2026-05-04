"""Spec §10 test 12 — AgentActionType enum stays exactly {EXECUTE_SWAP, WAIT, FINISH}.

This is a regression-lock against spec §6 non-goal 11 / §12 kill condition 9.
V0 must NOT add, remove, or rename any member.
"""
from src.db.schemas import AgentActionType


def test_agent_action_type_members_locked():
    members = {member.value for member in AgentActionType}
    assert members == {"EXECUTE_SWAP", "WAIT", "FINISH"}, (
        f"AgentActionType drifted in V0; got {members}. "
        "Spec §12 kill 9: rebalance V0 is decision-only and emits FINISH/WAIT only. "
        "No new members allowed."
    )
